from sched import *
from ipc import *
import gc

client_asm = """
CREATE_PORT
STORE a

PUSH 1
FETCH a
PUSH 1
SEND

FETCH a
RECV

PRINT

JMP 3

HALT
"""

def get_mem_stats():
    gc.collect()
    
    free = gc.mem_free()
    alloc = gc.mem_alloc()
    total = free + alloc
    
    usage_pct = (alloc / total) * 100
    
    return free, alloc, usage_pct

def print_info():
    free_b, alloc_b, pct = get_mem_stats()
    
    f_kb = free_b / 1024
    a_kb = alloc_b / 1024
    
    print(f" reallyMach ")
    print(f"{f_kb:.1f}")
    print(f"{a_kb:.1f} ({pct:.2f}%)\n")

def printer(msg, ipc):
    ipc.syscall_send(1, (msg[1], 0, "hello"))

def test_rmach():
    sched = PrioSched()
    ipc = rMachIPC()
    kernel = Kernel(sched, ipc)
    
    ipc.mk_py_h(printer)
    add_right(2, 1, SEND, None)
    
    kernel.spawn(2, 4, client_asm)
    
    print_info()
    
    kernel.kernel_loop() 

if __name__ == "__main__":
    test_rmach()
