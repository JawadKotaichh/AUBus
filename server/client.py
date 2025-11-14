import socket
from server import SERVER_HOST, SERVER_PORT


def main():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.connect((SERVER_HOST, SERVER_PORT))
        print("[CLIENT] Connected to server")
        data = sock.recv(1024)
        print("[CLIENT] Received:", data.decode(errors="ignore").strip())
        sock.sendall(b"hello server\n")
        echo = sock.recv(1024)
        print("[CLIENT] Echo from server:", echo.decode(errors="ignore").strip())


if __name__ == "__main__":
    main()
