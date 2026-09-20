"""gemini_error 測試：純函式，不打網路。"""
from commute_agent.tools.gemini_error import describe, is_retryable, status_code


class FakeError(Exception):
    """模仿 google-genai 的例外：訊息開頭就是狀態碼。"""


class TypedError(Exception):
    def __init__(self, code):
        super().__init__("something went wrong")
        self.code = code


def test_status_code_is_read_from_the_attribute_first():
    assert status_code(TypedError(429)) == 429


def test_status_code_falls_back_to_the_message():
    assert status_code(FakeError("402 RESOURCE_EXHAUSTED. {'error': {}}")) == 402


def test_no_status_code_at_all():
    assert status_code(FakeError("Connection reset by peer")) is None


def test_depleted_credit_says_what_to_do():
    # 只印 ClientError 的話，使用者永遠不會知道要去加值
    said = describe(FakeError("402 RESOURCE_EXHAUSTED. prepayment credits are depleted"))
    assert "額度" in said and "402" in said


def test_each_known_status_gets_its_own_wording():
    assert "金鑰無效" in describe(FakeError("401 UNAUTHENTICATED"))
    assert "速率" in describe(FakeError("429 RESOURCE_EXHAUSTED"))
    assert "流量過大" in describe(FakeError("503 UNAVAILABLE"))


def test_unknown_errors_keep_their_own_message():
    said = describe(FakeError("Connection reset by peer"))
    assert "FakeError" in said and "Connection reset" in said


def test_server_errors_are_worth_retrying():
    assert is_retryable(FakeError("503 UNAVAILABLE")) is True
    assert is_retryable(FakeError("500 INTERNAL")) is True


def test_account_problems_are_not_worth_retrying():
    # 額度用完、金鑰不對，再試一次也是同一個錯，只是讓使用者多等
    assert is_retryable(FakeError("402 RESOURCE_EXHAUSTED")) is False
    assert is_retryable(FakeError("401 UNAUTHENTICATED")) is False
    assert is_retryable(FakeError("404 NOT_FOUND")) is False


def test_an_unrecognised_error_is_retried_once():
    # 逾時與連線中斷都認不出狀態碼，多試一次的代價只有幾秒
    assert is_retryable(FakeError("Connection reset by peer")) is True
