"""Run the optional WhisperLive CPU comparison server."""
import argparse
import os


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=9090)
    parser.add_argument("--omp_num_threads", type=int, default=12)
    args = parser.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", str(args.omp_num_threads))

    from whisper_live.server import TranscriptionServer

    TranscriptionServer().run("localhost", port=args.port, backend="faster_whisper")


if __name__ == "__main__":
    main()
