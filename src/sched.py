from ipc import *
from proc import *
import gc

_msb_table = (-1, 0, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3)

class PrioSched:
    def __init__(self, max_prio=16):
        self.max_prio = max_prio
        self.active_queues = [[] for _ in range(self.max_prio + 1)]
        self.expired_queues = [[] for _ in range(self.max_prio + 1)]
        self.active_mask = 0
        self.expired_mask = 0
        self.task_slices = {}
        self.default_slice = 2

    def create_proc(self, pid, prio):
        self.task_slices[pid] = self.default_slice
        
        while prio >= len(self.active_queues):
            self.active_queues.append([])
            self.expired_queues.append([])
        
        self.active_queues[prio].append(pid)
        self.active_mask |= (1 << prio)
        
    def tick(self, pid):
        if pid not in self.task_slices:
            self.task_slices[pid] = self.default_slice
            
        self.task_slices[pid] -= 1
        if self.task_slices[pid] <= 0:
            self.task_slices[pid] = self.default_slice
            return True
        return False

    def get_prio_fast(self, mask):
        if mask == 0:
            return -1
        res = 0
        m = mask
        if m >= 256: 
            m >>= 8
            res += 8
        if m >= 16:
            m >>= 4
            res += 4
        return res + _msb_table[m & 0x0F]

    def wake_up(self, pid, prio):
        self.active_queues[prio].insert(0, pid)
        self.active_mask |= (1 << prio)

    def get_next_proc(self):
        if self.active_mask == 0:
            if self.expired_mask == 0: 
                return None
            self.active_queues, self.expired_queues = self.expired_queues, self.active_queues
            self.active_mask, self.expired_mask = self.expired_mask, self.active_mask

        p = self.get_prio_fast(self.active_mask)
        queue = self.active_queues[p]
        pid = queue.pop(0)
        
        if not queue:
            self.active_mask &= ~(1 << p)
            
        self.expired_queues[p].append(pid)
        self.expired_mask |= (1 << p)

        return pid

class Kernel:
    def __init__(self, scheduler, ipc):
        self.sched = scheduler
        self.asm = Assembler()
        self.ipc = ipc
        self.procs = {}

    def set_bind(self, pid, event, callback):
        if pid in self.procs:
            self.procs[pid]['state'].bind(event, callback)

    def spawn(self, pid, prio, code):
        binary = self.asm.assemble(code)
        vm = VirtualMachine(self.ipc, pid)
        vm.load_prog(binary)
        
        gc.collect()
        
        self.procs[pid] = {
            'state': ProcessState(pid),
            'prio': prio,
            'vm': vm,
            'closed_count': 0,
        }
        
        self.procs[pid]['state'].bind('MACH_MSG_READY', lambda p, e: self.sched.wake_up(p, self.procs[p]['prio']))
        self.sched.create_proc(pid, prio)
        
    def exit_proc(self, pid):
        self.ipc.cleanup_process(pid)

        del self.procs[pid]
        del self.sched.task_slices[pid]
        
        for q_list in self.sched.active_queues + self.sched.expired_queues:
            if pid in q_list:
                q_list.remove(pid)

    def run_task(self, vm, big_f, p_info,
                 ps, system_pids, pid):
        try:
            quantum = (len(vm.program) >> 3) - 8
                
            res = None
                
            if big_f:
                res = (quantum > 0) * quantum + (not quantum > 0) * 8
            else:
                res = (quantum > 0) * quantum + (not quantum > 0) * len(vm.program)

            r = vm.make_step(res)
                
            if vm.state == WAITING:
                ps.transition('MACH_MSG_WAIT')
            elif vm.state == CLOSED:
                self.exit_proc(pid)
            return r
        except:
            if p_info['closed_count'] == 3 and (system_pids and not pid in system_pids):
                ps.transition('CLOSED')
                if pid in self.procs:
                    self.exit_proc(pid)
            else:
                p_info['closed_count'] += 1

    def kernel_loop(self, system_pids=None, big_f=False):
        while self.procs:
            try:
                pid = self.sched.get_next_proc()
            except:
                continue

            p_info = self.procs[pid]
            ps = p_info['state']
            
            if ps.current == WAITING:
                continue
        
            ps.transition('RUNNING')
            
            vm = p_info['vm']

            target_pid = self.run_task(vm, big_f, p_info, ps, system_pids, pid)

            if target_pid in self.procs:
                passes = 0
                current_target = target_pid
                
                while current_target in self.procs and passes < 3:
                    tp_info = self.procs[current_target]

                    if tp_info['vm'].ended == 1:
                        break
                    
                    next_target = self.run_task(tp_info['vm'], big_f, tp_info,
                                                tp_info['state'], system_pids, current_target)
                    passes += 1
                    
                    if next_target in self.procs and next_target != current_target:
                        current_target = next_target
                    else:
                        break

            if ps.current == 'RUNNING':
                if self.sched.tick(pid):
                    ps.transition('READY')
