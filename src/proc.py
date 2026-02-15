from consts import *

CLOSED, RUNNING, WAITING, READY = 1, 2, 3, 4

class ProcessState:
    def __init__(self, pid):
        self.pid = pid
        self.current = READY
        self.bindings = {}

    def bind(self, event, callback):
        self.bindings[event] = callback

    def transition(self, event):
        if event in self.bindings:
            self.bindings[event](self.pid, event)

        if event == 'MACH_MSG_WAIT':
            self.current = WAITING
        elif event == 'MACH_MSG_READY':
            self.current = READY
        elif event == 'RUNNING':
            self.current = RUNNING
        elif event == 'CLOSED':
            self.current = CLOSED

FETCH, STORE, PUSH, POP, ADD, SUB, MUL, DIV, LT, GT, EQ, NOTEQ, JZ, JNZ, JMP, RECV, SEND = range(17)
LIST, DICT, INDEX, CREATE_PORT, APPEND, RETURN, PRINT, HALT = range(17, 25)
 
class Assembler:
    def __init__(self):
        self.ops = {
            'FETCH': (0, 2), 'STORE': (1, 2), 'PUSH': (2, 2), 'POP': (3, 1),
            'ADD': (4, 1), 'SUB': (5, 1), 'MUL': (6, 1),  'DIV': (7, 1),
            'LT': (8, 1), 'GT': (9, 1), 'EQ': (10, 1),  'NOTEQ': (11, 1),
            'JZ': (12, 2), 'JNZ': (13, 2), 'JMP': (14, 2), 'RECV': (15, 1),
            'SEND': (16, 1), 'HALT': (24, 1), 'PRINT': (23, 1),
            'LIST': (17, 1), 'DICT': (18, 1), 'INDEX': (19, 1), 
            'CREATE_PORT': (20, 1), 'APPEND': (21, 2), 'RETURN': (22, 1)
        }
        self.macros = {}

    def atom(self, val):
        if not isinstance(val, str):
            return val
        s = val.lstrip('-')
        if s.isdigit():
            return int(val)
        elif '.' in s and s.replace('.', '', 1).isdigit():
            return float(val)
        return val

    def assemble(self, source):
        raw_lines = [l.strip() for l in source.split('\n') if l.strip() and not l.startswith('#')]
        expanded_lines = []
        current_macro_name = None
        
        for line in raw_lines:
            if line.startswith('.func '):
                current_macro_name = line.split()[1].upper()
                self.macros[current_macro_name] = []
                continue
            if line == '.end':
                current_macro_name = None
                continue
            
            if current_macro_name:
                self.macros[current_macro_name].append(line)
            else:
                parts = line.split()
                cmd_potential = parts[0].upper()
                if cmd_potential in self.macros:
                    expanded_lines.extend(self.macros[cmd_potential])
                else:
                    expanded_lines.append(line)

        bytecode = []
        for line in expanded_lines:
            parts = line.split('#')[0].strip().split()
            if not parts: continue
            
            cmd = parts[0].upper()
            if cmd not in self.ops:
                bytecode.append(HALT)
                break
                
            op_code, length = self.ops[cmd]
            bytecode.append(op_code)
            
            if length == 2:
                if len(parts) > 1:
                    bytecode.append(self.atom(parts[1]))
                else:
                    bytecode.append(0)
                    
        return bytecode
    
CLOSED, RUNNING, WAITING = 1, 2, 3

class VirtualMachine:
    def __init__(self, ipc, pid):
        self.ipc = ipc
        self.pid = pid
        self.program = []
        self.pc = 0
        self.stack = []
        self.env = {'exitcode': 0}
        self.state = CLOSED
        self.ended = 0
        self.ports_count = 0
        
    def load_prog(self, bytecode):
        self.program = bytecode
        self.pc = 0
        self.stack = []
        self.env = {'exitcode': 0}
        self.ports_count = 0
    
    def make_step(self, quantum=3):
        if self.ended == 1:
            return 0
        self.state = RUNNING
        
        pc = self.pc
        stack = self.stack
        env = self.env
        program = self.program

        if pc >= len(self.program):
            self.state = CLOSED
            self.program = []
            return 0
        
        for i in range(quantum):
            if pc >= len(self.program):
                self.state = CLOSED
                self.program = []
                return 0
            if len(stack) > 32:
                self.state = CLOSED
                self.ended = 1
                return 0
                
            op = program[pc]
            if pc < len(program) - 1:
                arg = program[pc + 1]
            
            if op == FETCH:
                try:
                    if env[arg]:
                        stack.append(env[arg])
                    else:
                        stack.append(0)
                except:
                    stack.append(0)
                pc += 2
            elif op == STORE:
                value = stack.pop()
                env[arg] = value
                pc += 2
            elif op == PUSH:
                stack.append(arg)
                pc += 2
            elif op == ADD:
                stack[-2] += stack[-1]
                stack.pop()
                pc += 1
            elif op == SUB:
                stack[-2] -= stack[-1]
                stack.pop()
                pc += 1
            elif op == MUL:
                stack[-2] *= stack[-1]
                stack.pop()
                pc += 1
            elif op == DIV:
                stack[-2] //= stack[-1]
                stack.pop()
                pc += 1
            elif op == LT:
                if stack[-2] < stack[-1]:
                    stack[-2] = 1
                else:
                    stack[-2] = 0
                stack.pop()
                pc += 1
            elif op == GT:
                if stack[-2] > stack[-1]:
                    stack[-2] = 1
                else:
                    stack[-2] = 0
                stack.pop()
                pc += 1
            elif op == EQ:
                if stack[-2] == stack[-1]:
                    stack[-2] = 1
                else:
                    stack[-2] = 0
                stack.pop()
                pc += 1
            elif op == NOTEQ:
                if stack[-2] != stack[-1]:
                    stack[-2] = 1
                else:
                    stack[-2] = 0
                stack.pop()
                pc += 1
            elif op == POP:
                stack.pop()
                pc += 1
            elif op == JZ:
                if stack.pop() == 0:
                    pc = arg
                else:
                    pc += 2
                continue
            elif op == JNZ:
                if stack.pop() != 0:
                    pc = arg
                else:
                    pc += 2
                continue
            elif op == JMP:
                pc = arg
                continue
            elif op == PRINT:
                val = stack.pop()
                print(val)
                pc += 1
            elif op == SEND:
                remote_port = stack.pop()
                local_port = stack.pop()
                val = stack.pop()
                
                status, target_pid = self.ipc.send(self.pid, (remote_port, local_port, val))
                
                pc += 1
                
                if status == PORT_HANDOFF:
                    break
            elif op == RECV:
                port_id = stack.pop()
                    
                msg, status = self.ipc.receive(self.pid, port_id)
                
                if status == PORT_BUFFERED:
                    self.state = WAITING
                    stack.append(port_id)
                    break
                elif status == PORT_DIED_NAME:
                    stack.append('DIED')
                elif status == PORT_SUCCESS:
                    stack.append(msg)
                else:
                    stack.append(0)
                    
                pc += 1
            elif op == LIST:
                count = stack.pop()
                
                res = []
                for i in range(count):
                    val = stack.pop()
                    res.append(val)
                    
                res = res[::-1]
                stack.append(res)
                pc += 1
            elif op == DICT:
                count = stack.pop()
                
                raw_data = []
                for _ in range(count):
                    val = stack.pop()
                    raw_data.append(val)
                
                res = {}
                
                res = {}
                i = len(raw_data) - 1
                while i > 0:
                    key = raw_data[i]
                    val = raw_data[i - 1]
                    res[key] = val
                    i -= 2
                        
                stack.append(res)
                pc += 1
            elif op == INDEX:
                idx = stack.pop()
                obj = stack.pop()
                
                try:
                    res = obj[idx]
                except:
                    res = 0

                stack.append(res)
                pc += 1
            elif op == APPEND:
                obj = env[arg]
                if type(obj) is dict:
                    key = stack.pop()
                    val = stack.pop()
                    obj[key] = val
                    stack.append(obj)
                elif type(obj) is list:
                    val = stack.pop()
                    obj.append(val)
                    stack.append(obj)
                pc += 2
            elif op == CREATE_PORT:
                self.ports_count += 1
                if self.ports_count > 8:
                    pc += 1
                    stack.append(-1)
                    continue
                p_id = self.ipc.create_port(self.pid)
                stack.append(p_id)
                pc += 1
            elif op == RETURN:
                pc += 1
                break
            elif op == HALT:
                self.state = CLOSED
                self.ended = 1
                return env['exitcode']

        self.pc = pc
        self.stack = stack
        self.env = env

        return i

