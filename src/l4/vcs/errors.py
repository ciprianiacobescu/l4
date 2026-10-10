class GitError(Exception):
    def __init__(self, argv: list[str], returncode: int, stderr: str) -> None:
        self.argv = argv
        self.returncode = returncode
        self.stderr = stderr
        first = stderr.strip().splitlines()[:1]
        super().__init__(f"{' '.join(argv)} failed ({returncode})" + (f": {first[0]}" if first else ""))
