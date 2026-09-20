def pytest_addoption(parser):
    parser.addoption(
        "--exe",
        action="store",
        default=None,
        help="Path to the packaged CertificateAutomation executable",
    )

