#include "gcov_uart_vfs.h"
#include "esp_vfs.h"
#include "esp_vfs_ops.h"
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define VFS_MOUNT "/gcov"
#define GCOV_MAX_FDS 4

static bool s_fd_used[GCOV_MAX_FDS];

static const char s_b64[] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

static void b64_print(const uint8_t* data, size_t len) {
  for (size_t i = 0; i < len; i += 3) {
    uint8_t a = data[i];
    uint8_t b = (i + 1 < len) ? data[i + 1] : 0;
    uint8_t c = (i + 2 < len) ? data[i + 2] : 0;
    size_t rem = len - i;
    putchar(s_b64[a >> 2]);
    putchar(s_b64[((a & 0x3) << 4) | (b >> 4)]);
    putchar(rem > 1 ? s_b64[((b & 0xf) << 2) | (c >> 6)] : '=');
    putchar(rem > 2 ? s_b64[c & 0x3f] : '=');
  }
}

static int gcov_open_p(void* ctx, const char* path, int flags, int mode) {
  (void)ctx;
  (void)flags;
  (void)mode;
  for (int fd = 0; fd < GCOV_MAX_FDS; fd++) {
    if (!s_fd_used[fd]) {
      s_fd_used[fd] = true;
      printf("GCOV_FILE_START:%s\n", path);
      fflush(stdout);
      return fd;
    }
  }
  errno = ENFILE;
  return -1;
}

static ssize_t gcov_write_p(void* ctx, int fd, const void* data, size_t size) {
  (void)ctx;
  if (fd < 0 || fd >= GCOV_MAX_FDS || !s_fd_used[fd]) {
    errno = EBADF;
    return -1;
  }
  printf("GCOV_B64:");
  b64_print((const uint8_t*)data, size);
  printf("\n");
  fflush(stdout);
  return (ssize_t)size;
}

static int gcov_close_p(void* ctx, int fd) {
  (void)ctx;
  if (fd < 0 || fd >= GCOV_MAX_FDS || !s_fd_used[fd]) {
    errno = EBADF;
    return -1;
  }
  s_fd_used[fd] = false;
  printf("GCOV_FILE_END\n");
  fflush(stdout);
  return 0;
}

static off_t gcov_lseek_p(void* ctx, int fd, off_t offset, int whence) {
  (void)ctx;
  (void)fd;
  (void)offset;
  (void)whence;
  return 0;
}

static const esp_vfs_fs_ops_t s_gcov_vfs = {
    .open_p = &gcov_open_p,
    .write_p = &gcov_write_p,
    .close_p = &gcov_close_p,
    .lseek_p = &gcov_lseek_p,
};

void gcov_uart_vfs_init(void) {
  memset(s_fd_used, 0, sizeof(s_fd_used));
  ESP_ERROR_CHECK(esp_vfs_register_fs(VFS_MOUNT, &s_gcov_vfs,
                                      ESP_VFS_FLAG_STATIC | ESP_VFS_FLAG_CONTEXT_PTR, NULL));
}

#define _GCOV_STRIP_STR(x) #x
#define GCOV_STRIP_STR(x) _GCOV_STRIP_STR(x)
extern void __gcov_dump(void) __attribute__((weak));

void gcov_uart_vfs_dump(void) {
  if (!__gcov_dump) return;
  gcov_uart_vfs_init();
  setenv("GCOV_PREFIX", "/gcov", 1);
  setenv("GCOV_PREFIX_STRIP", GCOV_STRIP_STR(GCOV_PREFIX_STRIP_COUNT), 1);
  __gcov_dump();
  printf("GCOV_DUMP_DONE\n");
  fflush(stdout);
}
