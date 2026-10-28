; ASR-owned x64 refresh bridge. Offsets below are patched as signed RIP-relative references.
mov dword ptr [rbp+0x104], eax
sub rsp, 0x138
mov [rsp+0x60], rax
mov [rsp+0x68], rcx
mov [rsp+0x70], rdx
mov [rsp+0x78], r8
mov [rsp+0x80], r9
mov [rsp+0x88], r10
mov [rsp+0x90], r11
mov [rsp+0x98], rbx
mov [rsp+0xa0], rsi
mov [rsp+0xa8], rdi
movups [rsp+0xd0], xmm0
movups [rsp+0xe0], xmm1
movups [rsp+0xf0], xmm2
movups [rsp+0x100], xmm3
movups [rsp+0x110], xmm4
movups [rsp+0x120], xmm5
inc dword ptr [rip+0] ; @data 0
and dword ptr [rip+0], 7 ; @data 0
jnz finished
cmp dword ptr [rip+0], 1 ; @data 4
je check_marker
xor ecx, ecx
lea rdx, [rip+0] ; @data 0x20
mov r8d, 448
call qword ptr [rip+0] ; @rva 0x61548d8
test eax, eax
jz finished
cmp eax, 448
jae finished
lea rdi, [rip+0] ; @data 0x20
mov ecx, eax
strip_name:
dec ecx
js finished
cmp word ptr [rdi+rcx*2], 0x5c
jne strip_name
lea rdi, [rdi+rcx*2+2]
lea rsi, [rip+0] ; @data 0x500
mov ecx, 20
copy_prefix:
mov dx, [rsi]
mov [rdi], dx
add rsi, 2
add rdi, 2
dec ecx
jnz copy_prefix
call qword ptr [rip+0] ; @rva 0x61547f8
mov ecx, 7
hex_digit:
mov edx, eax
and edx, 15
cmp edx, 9
jbe decimal_digit
add edx, 0x57
jmp write_digit
decimal_digit:
add edx, 0x30
write_digit:
mov word ptr [rdi+rcx*2], dx
shr eax, 4
dec ecx
jns hex_digit
mov word ptr [rdi+16], 0
mov dword ptr [rip+0], 1 ; @data 4
check_marker:
lea rcx, [rip+0] ; @data 0x20
call qword ptr [rip+0] ; @rva 0x6154180
cmp eax, -1
je finished
test eax, 0x10
jnz finished
lea rcx, [rsp+0x20]
call 0x827b00 ; @call 0x827b00
; OptionsState contains its UI model at +0xb0; model.AddOns is +0x60.
mov rbx, [rbp+0xf8]
mov rsi, [rbx+0x118]
mov rdi, [rbx+0x120]
test rdi, rdi
jz free_rows
drop_row:
mov rcx, rsi
call 0x1401e0 ; @call 0x1401e0
add rsi, 104
dec rdi
jnz drop_row
free_rows:
mov rdx, [rbx+0x110]
test rdx, rdx
jz replace_rows
imul rdx, rdx, 104
mov rcx, [rbx+0x118]
mov r8d, 8
call 0x21d0 ; @call 0x21d0
replace_rows:
movups xmm0, [rsp+0x20]
movups [rbx+0x110], xmm0
mov rax, [rsp+0x30]
mov [rbx+0x120], rax
mov dword ptr [rbx+0x1bc], 0
inc dword ptr [rbx+0x1b8]
mov rax, [rbp+0xe0]
mov edx, [rbp+0x104]
mov [rax], edx
lea rcx, [rip+0] ; @data 0x20
call qword ptr [rip+0] ; @rva 0x6154158
finished:
movups xmm0, [rsp+0xd0]
movups xmm1, [rsp+0xe0]
movups xmm2, [rsp+0xf0]
movups xmm3, [rsp+0x100]
movups xmm4, [rsp+0x110]
movups xmm5, [rsp+0x120]
mov rax, [rsp+0x60]
mov rcx, [rsp+0x68]
mov rdx, [rsp+0x70]
mov r8, [rsp+0x78]
mov r9, [rsp+0x80]
mov r10, [rsp+0x88]
mov r11, [rsp+0x90]
mov rbx, [rsp+0x98]
mov rsi, [rsp+0xa0]
mov rdi, [rsp+0xa8]
add rsp, 0x138
ret


