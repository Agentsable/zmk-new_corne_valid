"""Generated ZMK Studio RPC bindings — do not edit by hand.

Regenerate after bumping the zmk-studio-messages revision in zmk/app/west.yml:

    python -m grpc_tools.protoc \
      -I modules/msgs/zmk-studio-messages/proto/zmk \
      --python_out=tools/flasher/zmk_proto \
      modules/msgs/zmk-studio-messages/proto/zmk/*.proto

Committed rather than generated at runtime so run.sh needs only pip, not protoc.
The generated gencode version must not exceed the protobuf runtime in .venv.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
