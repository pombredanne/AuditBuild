CC	:= gcc

.PHONY: all
all: hello.exe

hello.exe: hello.o goodbye.o
	$(CC) -o $@ $^

%.o: %.c
	$(CC) -c $<

.PHONY: clean
clean::
	$(RM) hello.exe *.o

.PHONY: rt
rt: clean all
