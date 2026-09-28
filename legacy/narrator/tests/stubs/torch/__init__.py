from _stublog import record
def manual_seed(n): record({"call": "manual_seed", "seed": int(n)})
class _Cuda:
    @staticmethod
    def is_available(): return False
    @staticmethod
    def empty_cache(): pass
    @staticmethod
    def get_device_capability(*a): return (8, 6)
    @staticmethod
    def get_device_name(*a): return "stub"
cuda = _Cuda()
float32 = "float32"
bfloat16 = "bfloat16"
class _NoGrad:
    def __enter__(self): return self
    def __exit__(self, *a): return False
def no_grad(): return _NoGrad()
