"""
Some useful decorator functions
"""
import time

def timeit(func):
    """Decorator used to time the execution of a function"""
    def timefunc(*args, **kwargs):
        """wrapper"""
        t_1 = time.time()
        t_2 = time.clock()
        res = func(*args, **kwargs)
        t_3 = time.clock()
        t_4 = time.time()
        print "%s: %.2fms (time) %.2fms (clock)" % \
              (func.func_name, 1000*(t_3 - t_2), 1000*(t_4 - t_1))
        return res
    return timefunc
