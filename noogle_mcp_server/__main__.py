# Ensure tools are registered by importing them
from noogle_mcp_server.tools import mcp  # noqa: F401


def main():
    mcp.run()


if __name__ == "__main__":
    main()
