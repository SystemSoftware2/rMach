from collections import deque
from consts import *

rights = {}

SEND = 0b01
RECEIVE = 0b11
SERVER = 0b100

dead_ports = 0

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

def ports_add(port_id):
    global dead_ports
    dead_ports |= (1 << port_id)
    
def ports_get(port_id):
    if (dead_ports >> port_id) & 1:
        return port_id
    return None

class rMachPort:
    def __init__(self):
        self.ref_count = 0
        self.messages = deque((), 32)
        self.blocked_threads = deque((), 32)
        self.rights_buffer = deque((), 32)

    def retain(self):
        self.ref_count += 1

    def release(self, port_id, ipc):
        self.ref_count -= 1
        if self.ref_count == 0:
            ipc.destroy_port(port_id)

    def put(self, data, right_id=None):
        packet = (data, right_id)
        if self.blocked_threads:
            target = self.blocked_threads.popleft()
            self.messages.append(packet)
            return target
        
        self.messages.append(packet)
        return None

    def read(self, thread_id):
        if self.messages:
            return self.messages.popleft(), PORT_SUCCESS
        
        self.blocked_threads.append(thread_id)
        return None, PORT_BUFFERED

class rMachIPC:
    def __init__(self):
        self.ports = {}
        self.port_counter = 0
        self.py_handlers = {}

    def create_port(self, pid):
        self.port_counter += 1
        p_id = self.port_counter
        port = rMachPort()
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
        if ports_get(remote_port):
            return PORT_DIED_NAME, None
        
        target_port = self.ports.get(remote_port)
        
        if not check(pid, remote_port, SEND):
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
                    pass
                return PORT_SUCCESS, None
            return PORT_ERR_INVALID_NAME, None
        
        target_pid = target_port.put(msg[2], right_id=msg[1])
        if target_pid:
            return PORT_HANDOFF, target_pid
        return PORT_BUFFERED, None
    
    def syscall_send(self, py_handler, msg):
        if not len(msg) == 3:
            return PORT_ERR_INVALID_NAME, None
        
        if py_handler not in self.py_handlers:
            return PORT_ERR_INVALID_NAME, None
        
        remote_port_id = msg[0]
        if ports_get(remote_port_id):
            return PORT_DIED_NAME, None
    
        if not check(py_handler, remote_port_id, SERVER):
            return PORT_ERR_NO_RIGHT, None
        
        target_port = self.ports.get(remote_port_id)
        if not target_port:
            return PORT_ERR_INVALID_NAME, None
        
        target_port.put(msg[2], right_id=msg[1])
        consume_right(py_handler, remote_port_id, target_port, self)
        
        return PORT_SUCCESS, None
    
    def receive(self, pid, port_id):
        if ports_get(port_id):
            return None, PORT_DIED_NAME
        
        port_obj = self.ports.get(port_id)
        if not port_obj:
            return None, PORT_ERR_INVALID_NAME
        
        if not check(pid, port_id, RECEIVE):
            return None, PORT_ERR_NO_RIGHT

        packet, status = port_obj.read(pid)
        if status == PORT_SUCCESS:
            data_payload, transfer_id = packet
            if transfer_id:
                target_port_obj = self.ports.get(transfer_id)
                if target_port_obj:
                    add_right(pid, transfer_id, SEND, target_port_obj)
            return data_payload, PORT_SUCCESS
        
        return None, status

    def transfer_right(self, src_pid, dest_port_id, port_id):
        if check(src_pid, port_id, SEND):
            target_port = self.ports.get(dest_port_id)
            if target_port:
                target_port.rights_buffer.append(port_id)
                
    def cleanup_process(self, pid):
        prefix = pid << 5
        for key in [k for k in rights if (k & ~0x1F) == prefix]:
            port_id = key & 0x1F
            port_obj = self.ports.get(port_id)
            if port_obj:
                port_obj.release(port_id, self)
            if key in rights:
                del rights[key]

    def destroy_port(self, port_id):
        if port_id in self.ports:
            del self.ports[port_id]
            keys_to_del = [k for k in rights if (k & 0x1F) == port_id]
            for k in keys_to_del:
                del rights[k]
            ports_add(port_id)
            return PORT_EXTINGUISHED
        return PORT_ERR_INVALID_NAME
