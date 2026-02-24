from collections import deque
from consts import *

rights = {}

SEND = 0b01
RECEIVE = 0b11
SERVER = 0b100

def add_right(pid, port_id, rtype, port):
    key = (pid << 16) | port_id
    
    if key in rights:
        if not (rights[key] & rtype):
            rights[key] |= rtype
    else:
        rights[key] = rtype
        if port is not None:
            port.retain()
    
    return True

def consume_right(pid, port_id, port, ipc):
    key = (pid << 16) | port_id
    right = rights.get(key, 0)
    
    if right & SERVER:
        new_rights = rights[key] & (~SERVER)
        if new_rights == 0:
            del rights[key]
        else:
            rights[key] = new_rights
        port.release(port_id, ipc)
        return True
    return False

def check(pid, port_id, required_perm):
    return (rights.get((pid << 16) | port_id, 0) & required_perm) == required_perm

class rMachPort:
    def __init__(self, own):
        self.owner_pid = own
        self.ref_count = 0
        self.messages = deque((), 32)
        self.blocked = None

    def retain(self):
        self.ref_count += 1

    def release(self, port_id, ipc):
        self.ref_count -= 1
        if self.ref_count == 0:
            ipc.destroy_port(port_id)

    def put(self, data):
        if len(self.messages) >= 32:
            return 
        
        if self.blocked:
            self.blocked = False
        
        self.messages.append(data)
        return self.owner_pid

    def read(self):
        if self.messages:
            return self.messages.popleft(), PORT_SUCCESS
        
        self.blocked = True
        return None, PORT_BUFFERED

class rMachIPC:
    def __init__(self):
        self.ports = {}
        self.port_counter = 0
        self.py_handlers = {}
        self.sched = None

    def create_port(self, pid):
        self.port_counter += 1
        p_id = self.port_counter
        port = rMachPort(pid)
        self.ports[p_id] = port
        add_right(pid, p_id, RECEIVE, port)
        return p_id
    
    def mk_py_h(self, func):
        self.port_counter += 1
        self.py_handlers[self.port_counter] = func
        return self.port_counter
        
    def send(self, pid, msg):
        if not len(msg) == 3:
            return PORT_ERR_INVALID_NAME, None
        
        remote_port = msg[0]
        
        target_port = self.ports.get(remote_port)
        
        if not (check(pid, remote_port, SEND) or \
            check(pid, remote_port, SERVER)):
                return PORT_ERR_NO_RIGHT, None
        
        if not target_port:
            if remote_port in self.py_handlers:
                if msg[1]:
                    reply_port_obj = self.ports.get(msg[1])
                    if reply_port_obj:
                        add_right(remote_port, msg[1], SERVER, reply_port_obj)
                try:
                    self.py_handlers[remote_port](msg, self)
                except:
                    self.syscall_send(remote_port, (msg[1], 0, HANDLER_ERROR))
                return PORT_SUCCESS, None
            return PORT_ERR_INVALID_NAME, None
        
        target_pid = target_port.put(msg[2])

        consume_right(pid, remote_port, target_port, self)
        
        if msg[1]:
            reply_port_obj = self.ports.get(msg[1], 0)
            self.transfer_right(pid, target_port.owner_pid, msg[1])

        return PORT_HANDOFF, target_pid
  
    def syscall_send(self, py_handler, msg):
        if not len(msg) == 3:
            return PORT_ERR_INVALID_NAME
        
        if py_handler not in self.py_handlers:
            return PORT_ERR_INVALID_NAME
        
        remote_port_id = msg[0]
    
        if not check(py_handler, remote_port_id, SERVER):
            return PORT_ERR_NO_RIGHT
        
        target_port = self.ports.get(remote_port_id)
        if not target_port:
            return PORT_ERR_INVALID_NAME
        
        target_port.put(msg[2])
        consume_right(py_handler, remote_port_id, target_port, self)

        if target_port.blocked:
            target_port.blocked = False
            self.sched.wake_up(target_port.owner_pid,
                               self.getprio(target_port.owner_pid))
            
        if msg[1]:
            reply_port_obj = self.ports.get(msg[1], 0)
            self.transfer_right(py_handler, target_port.owner_pid, msg[1])
        
        return PORT_SUCCESS
    
    def receive(self, pid, port_id):
        port_obj = self.ports.get(port_id)
        if not port_obj:
            return None, PORT_ERR_INVALID_NAME
        
        if not check(pid, port_id, RECEIVE):
            return None, PORT_ERR_NO_RIGHT

        packet, status = port_obj.read()
        if status == PORT_SUCCESS:
            return packet, PORT_SUCCESS
        
        return None, status

    def transfer_right(self, src_pid, dest_pid, port_id):
        if check(src_pid, port_id, SEND):
            if port_id in self.ports:
                add_right(dest_pid, port_id, SEND, self.ports[port_id])
                
    def cleanup_process(self, pid):
        for key in [k for k in rights if (k >> 16) == pid]:
            port_id = key & 0xFFFF
            port_obj = self.ports.get(port_id)
            if port_obj:
                port_obj.release(port_id, self)
            if key in rights:
                if rights[key] & RECEIVE:
                    self.destroy_port(port_id)
                else:
                    del rights[key]

    def destroy_port(self, port_id):
        if port_id in self.ports:
            del self.ports[port_id]
            keys_to_del = [k for k in rights if (k & 0xFFFF) == port_id]
            for k in keys_to_del:
                del rights[k]
            return PORT_EXTINGUISHED
        return PORT_ERR_INVALID_NAME
