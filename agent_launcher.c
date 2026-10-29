/*
 * Launcher the launchd agent runs: starts a script with /bin/bash and waits.
 *
 * Why a separate program: macOS privacy permissions (such as reading the
 * Documents folder) are granted to the program launchd starts, and are
 * inherited by everything it runs. Granting Full Disk Access to this small,
 * named program ("SermonTranscriberAgent") covers the pipeline without
 * granting it to bash or Python for every other use.
 *
 * agent.sh compiles it once into the settings folder's bin/ and doesn't
 * rebuild it on updates, because a rebuilt program loses the permission.
 *
 * Usage: SermonTranscriberAgent script.sh [args...]
 */
#include <errno.h>
#include <spawn.h>
#include <stdio.h>
#include <sys/wait.h>

extern char **environ;

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "usage: %s script.sh [args...]\n", argv[0]);
        return 2;
    }

    char *args[argc + 1];
    args[0] = "/bin/bash";
    for (int i = 1; i < argc; i++) args[i] = argv[i];
    args[argc] = NULL;

    /* spawn + wait, not exec: the script must run as this program's child
       for the permission to apply to it */
    pid_t pid;
    int rc = posix_spawn(&pid, "/bin/bash", NULL, NULL, args, environ);
    if (rc != 0) {
        fprintf(stderr, "could not start /bin/bash: error %d\n", rc);
        return 1;
    }

    int status;
    while (waitpid(pid, &status, 0) < 0) {
        if (errno != EINTR) return 1;
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}
