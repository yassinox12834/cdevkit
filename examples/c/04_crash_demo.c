/* 04_crash_demo.c: crashes ON PURPOSE, to test how the launcher explains crashes.
   Run it with an argument to choose the crash (Arguments box in the launcher):
     null      write through a NULL pointer     -> access violation / SIGSEGV
     divide    integer division by zero         -> divide by zero / SIGFPE
     recurse   infinite recursion               -> stack overflow / SIGSEGV
     overflow  signed integer overflow (undefined behaviour). Silent by default;
               switch on "Stop on undefined behaviour" to make it stop.
   Standard: C99 or newer. */
#include <limits.h>
#include <stdio.h>
#include <string.h>

static volatile int limit = 1 << 30;  /* never reached: the stack runs out long before */

static int depth(int n) {
    volatile char buffer[1024];      /* volatile: stops the compiler removing the recursion */
    buffer[0] = (char)n;
    if (n == limit) {
        return 0;
    }
    return depth(n + 1) + buffer[0];
}

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "null";
    printf("crash mode: %s\n", mode);
    fflush(stdout);                  /* print before crashing */

    if (strcmp(mode, "null") == 0) {
        volatile int *volatile p = NULL;   /* volatile: the optimiser must keep the write */
        *p = 42;
    } else if (strcmp(mode, "divide") == 0) {
        volatile int one = 1, zero = 0;
        int result = one / zero;
        printf("%d\n", result);
    } else if (strcmp(mode, "recurse") == 0) {
        printf("%d\n", depth(0));
    } else if (strcmp(mode, "overflow") == 0) {
        volatile int big = INT_MAX;
        int result = big + argc;     /* undefined behaviour */
        printf("INT_MAX + %d = %d (this number is meaningless)\n", argc, result);
    } else {
        printf("unknown mode, use: null, divide, recurse or overflow\n");
        return 2;
    }
    printf("no crash happened\n");
    return 0;
}
