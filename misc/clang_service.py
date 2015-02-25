import threading
from clang import cindex

USEFUL_OPTS = ['-D', '-I']

def get_useful_args(flags):
    num = len(flags)
    p = 0

    useful_opts = []

    while p < num:
        prefix = flags[p][0:2]
        if prefix in USEFUL_OPTS:
            useful_opts.append(flags[p])
            if len(flags[p]) == 2:
                p += 1
                if p < num:
                    useful_opts.append(flags[p])

        p += 1

    return useful_opts


class ClangContext(object):

    def __init__(self, name):

        self.__name = name
        self.__tu_tick = [None, -1]
        self.__buffer_tick = [None, 0]

    def update_buffer(self, buffer, tick):
        self.__buffer_tick = [buffer, tick]

    def parse(self, idx, args, unsaved, tick):
        try:
            tu = idx.parse(
                self.__name,
                args,
                unsaved,
                options=cindex.TranslationUnit.PARSE_DETAILED_PROCESSING_RECORD)
        except:
            tu = None
        finally:
            self.__tu_tick = [tu, tick]

    @property
    def name(self):
        return self.__name

    @property
    def buffer(self):
        return self.__buffer_tick[0]

    @property
    def change_tick(self):
        return self.__buffer_tick[1]

    @property
    def current_tu(self):
        return self.__tu_tick[0]

    @property
    def parse_tick(self):
        return self.__tu_tick[1]

    @parse_tick.setter
    def parse_tick(self, value):
        self.__tu_tick[1] = value


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(
                Singleton,
                cls).__call__(*args,
                              **kwargs)
        return cls._instances[cls]


class ClangService(object):
    __metaclass__ = Singleton

    def __init__(self):
        self.__current_cc = None
        self.__cc_dict = {}
        self.__parsing_thread = None
        self.__is_running = False
        self.__cond = threading.Condition()
        self.__cindex = None
        self.__cdb = None

    def __del__(self):
        self.stop()

    def __get_useful_args(self, name):
        if not self.__cdb:
            return None

        ccmds = self.__cdb.getCompileCommands(name)

        if not ccmds:
            return None

        # if there is more than one commands, take the first one
        args = list(ccmds[0].arguments)

        return get_useful_args(args)

    def start(self, cdb_dir):
        if self.__cindex is None:
            try:
                self.__cindex = cindex.Index.create()
            except:
                return False

        if self.__parsing_thread:
            return True

        if cdb_dir:
            try:
                self.__cdb = cindex.CompilationDatabase.fromDirectory(cdb_dir)
            except:
                pass

        self.__is_running = True
        self.__parsing_thread = threading.Thread(target=self.__parsing_worker)
        self.__parsing_thread.start()

        return True

    def stop(self):
        if self.__parsing_thread:
            self.__is_running = False
            with self.__cond:
                self.__cond.notify()
            self.__parsing_thread.join()
            self.__parsing_thread = None

        self.__cc_dict.clear()
        self.__cindex = None

    def unregister(self, list):
        for name in list:
            if name in self.__cc_dict.keys():
                del self.__cc_dict[name]

    def register(self, list):
        for name in list:
            if name in self.__cc_dict.keys():
                continue

            self.__cc_dict[name] = ClangContext(name)

    def update_buffers(self, update_list, notify=True):
        for name, buffer, tick in update_list:
            cc = self.__cc_dict.get(name)
            if cc is None:
                continue

            cc.update_buffer(buffer, tick)

        if notify:
            with self.__cond:
                self.__cond.notify()

    def switch(self, name):
        cc = self.__cc_dict.get(name)
        if cc is None:
            return

        cc.parse_tick = -1
        self.__current_cc = cc
        with self.__cond:
            self.__cond.notify()

    def parse_all(self):
        tick = {}
        for cc in self.__cc_dict.values():
            tick[cc.name] = cc.change_tick

        unsaved = self.__gen_unsaved()

        for cc in self.__cc_dict.values():
            cc.parse(
                self.__cindex,
                self.__get_useful_args(cc.name),
                unsaved,
                tick[cc.name])

    def get_cc(self, name):
        return self.__cc_dict.get(name)

    def __gen_unsaved(self):
        unsaved = []
        for cc in self.__cc_dict.values():
            buffer = cc.buffer

            if buffer:
                unsaved.append((cc.name, buffer))

        return unsaved

    def __parsing_worker(self):
        while self.__is_running:
            cc = self.__current_cc

            if cc is None:
                continue

            if cc.parse_tick == cc.change_tick:
                with self.__cond:
                    self.__cond.wait()

                if cc.parse_tick == cc.change_tick:
                    continue

            try:
                tick = cc.change_tick
                unsaved = self.__gen_unsaved()
            except:
                pass

            cc.parse(self.__cindex, self.__get_useful_args(cc.name), unsaved, tick)
