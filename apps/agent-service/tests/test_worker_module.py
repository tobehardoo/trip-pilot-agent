from importlib.util import find_spec


def test_worker_package_exists() -> None:
    assert find_spec("trip_agent.worker") is not None


def test_worker_contract_and_processor_modules_exist() -> None:
    assert find_spec("trip_agent.worker.contracts") is not None
    assert find_spec("trip_agent.worker.processor") is not None


def test_worker_amqp_module_exists() -> None:
    assert find_spec("trip_agent.worker.amqp") is not None
