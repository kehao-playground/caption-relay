"""Run WhisperLive's built-in Chinese-to-English translation comparison."""
import argparse


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="medium")
    parser.add_argument("--file")
    args = parser.parse_args()

    from whisper_live.client import TranscriptionClient

    client = TranscriptionClient("localhost", 9090, lang="zh", translate=True,
                                 model=args.model)
    if args.file:
        client(args.file)
    else:
        client()


if __name__ == "__main__":
    main()
