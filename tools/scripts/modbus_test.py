from pymodbus.client import ModbusTcpClient

def main() -> int:
    host = "192.168.217.163"
    port = 502

    client = ModbusTcpClient(host=host, port=port)
    if not client.connect():
        print(f"Could not connect to {host}:{port}")
        return 1

    try:
        # Example: read 10 holding registers starting at address 0
        result = client.read_holding_registers(address=0, count=10)
        if result.isError():
            print(f"Modbus error: {result}")
            return 2

        print(f"Registers: {result.registers}")
        return 0
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
