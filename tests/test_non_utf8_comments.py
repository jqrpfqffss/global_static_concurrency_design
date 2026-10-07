import unittest

from clang import cindex as ci

from ecra.extract import tokens


class _Token:
    def __init__(self, kind, spelling=None):
        self.kind = kind
        self._spelling = spelling

    @property
    def spelling(self):
        if self._spelling is None:
            raise UnicodeDecodeError('utf-8', b'\xb0', 0, 1, 'invalid start byte')
        return self._spelling


class _Cursor:
    def get_tokens(self):
        return iter((_Token(ci.TokenKind.COMMENT),
                     _Token(ci.TokenKind.IDENTIFIER, 'value')))


class NonUtf8CommentTests(unittest.TestCase):
    def test_comment_spelling_is_not_decoded_or_counted_toward_limit(self):
        self.assertEqual(['value'], tokens(_Cursor()))
        self.assertEqual(['value'], tokens(_Cursor(), limit=1))


if __name__ == '__main__':
    unittest.main()
