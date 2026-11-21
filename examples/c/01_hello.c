/* 01_hello.c: the smallest test. Works with every C standard from C89.
   Expected output: Hello from C! then the standard number. */
#include <stdio.h>

int main(void) {
    printf("Hello from C!\n");
#ifdef __STDC_VERSION__
    printf("__STDC_VERSION__ = %ld\n", (long)__STDC_VERSION__);
#else
    printf("Compiled as C89/C90 (no __STDC_VERSION__)\n");
#endif
    return 0;
}
