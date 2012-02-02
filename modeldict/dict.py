from modeldict.base import PersistedDict
import time


class RedisDict(PersistedDict):
    """
    Dictionary-style access to a redis hash table. Populates a cache and a local
    in-memory to avoid multiple hits to the database.

    Functions just like you'd expect it::

        mydict = RedisDict('my_redis_key', Redis())
        mydict['test']
        >>> 'bar' #doctest: +SKIP

    """
    def __init__(self, keyspace, connection, *args, **kwargs):
        self.keyspace = keyspace
        self.conn = connection
        super(RedisDict, self).__init__(*args, **kwargs)
        self.__touch_last_updated()

    def persist(self, key, value):
        self.__touch_and_multi(('hset', (self.keyspace, key, value)))

    def depersist(self, key):
        self.__touch_and_multi(('hdel', (self.keyspace, key)))

    def persistents(self):
        return self.conn.hgetall(self.keyspace)

    def last_updated(self):
        return int(self.conn.get(self.__last_update_key) or 0)

    # TODO: setdefault always touches the last_updated value, even if the key
    # existed already.  It should only touch last_updated if the key did not
    # already exist
    def _setdefault(self, key, default=None):
        return self.__touch_and_multi(
            ('hsetnx', (self.keyspace, key, default)),
            ('hget', (self.keyspace, key)),
            returns=-1
        )

    def _pop(self, key, default=None):
        last_updated, value, key_existed = self.__touch_and_multi(
            ('hget', (self.keyspace, key)),
            ('hdel', (self.keyspace, key))
        )

        if key_existed:
            return value
        elif default:
            return default
        else:
            raise KeyError

    def __touch_and_multi(self, *args, **kwargs):
        """
        Runs each tuple tuple of (redis_cmd, args) in provided inside of a Redis
        MULTI block, plus an increment of the last_updated value, then executes
        the MULTI block.  If ``returns`` is specified, it returns that index
        from the results list.  If ``returns`` is None, returns all values.
        """

        with self.conn.pipeline() as pipe:
            pipe.incr(self.__last_update_key)
            {getattr(pipe, function)(*args) for function, args in args}
            results = pipe.execute()

            if kwargs.get('returns'):
                return results[kwargs.get('returns')]
            else:
                return results

    def __touch_last_updated(self):
        return self.conn.incr(self.__last_update_key)

    @property
    def __last_update_key(self):
        return self.keyspace + 'last_updated'


class ModelDict(PersistedDict):
    """
    Dictionary-style access to a model. Populates a cache and a local in-memory
    to avoid multiple hits to the database.

    Specifying ``instances=True`` will cause the cache to store instances rather
    than simple values.

    If ``auto_create=True`` accessing modeldict[key] when key does not exist will
    attempt to create it in the database.

    Functions in two different ways, depending on the constructor:

        # Given ``Model`` that has a column named ``foo`` where the value at
        # that column is "bar":

        mydict = ModelDict(Model, value_col='foo')
        mydict['test']
        >>> 'bar' #doctest: +SKIP

    If you want to use another key in the ModelDict besides the ``Model``s
    ``pk``, you may specify that in the constructor with ``key_col``.  For
    instance, if your ``Model`` has a column called ``id``, you can index into
    that column by passing ``key_col='id'`` in to the contructor:

        mydict = ModelDict(Model, key_col='id', value_col='foo')
        mydict['test']
        >>> 'bar' #doctest: +SKIP

    The constructor also takes a cache keyword argument, which is an object that
    responds to two methods, add and incr.  The cache object is used to manage
    the value for last_updated.  ``add`` is called on initialize to create the
    key if it does not exist with the default value, and ``incr`` is done to
    atomically update the last_updated value.

    """

    def __init__(self, manager, cache, key_col='key', value_col='value', *args, **kwargs):
        self.manager = manager
        self.cache = cache
        self.cache_key = 'last_updated'
        self.key_col = key_col
        self.value_col = value_col
        self.cache.add(self.cache_key, 1) # Only adds if key does not exist
        super(ModelDict, self).__init__(*args, **kwargs)


    def persist(self, key, val):
        instance, created = self.get_or_create(key, val)

        if not created and getattr(instance, self.value_col) != val:
            setattr(instance, self.value_col, val)
            instance.save()

        self.__touch_last_updated()

    def depersist(self, key):
        self.manager.get(**{self.key_col: key}).delete()
        self.__touch_last_updated()

    def persistents(self):
        return dict(
            self.manager.values_list(self.key_col, self.value_col)
        )

    def _setdefault(self, key, default=None):
        instance, created = self.get_or_create(key, default)

        if created:
            self.__touch_last_updated()

        return getattr(instance, self.value_col)

    def _pop(self, key, default=None):
        try:
            instance = self.manager.get(**{self.key_col: key})
            value = getattr(instance, self.value_col)
            instance.delete()
            self.__touch_last_updated()
            return value
        except self.manager.model.DoesNotExist:
            if default is not None:
                return default
            else:
                raise KeyError

    def get_or_create(self, key, val):
        return self.manager.get_or_create(
            defaults={self.value_col: val},
            **{self.key_col: key}
        )

    def last_updated(self):
        return self.cache.get(self.cache_key)

    def __touch_last_updated(self):
        self.cache.incr('last_updated')