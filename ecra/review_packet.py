"""Validate an entire Packet JSON while reading only receipt-check fields.

The model still receives the complete original Packet. This projection is
private to receipt validation; it must never be used to publish facts/Packets.
"""
import re

from .json_rows import RowReader

_STRING_SPECIAL=re.compile(r'["\\\x00-\x1f]')
_DIGITS=re.compile(r'[0-9]+')


class ReceiptReader(RowReader):
    def raw(self):
        while self.position>=len(self.buffer):
            if self.eof:return ''
            self.fill()
        return self.buffer[self.position]

    def string(self):
        self.take('"')
        while True:
            special=_STRING_SPECIAL.search(self.buffer,self.position)
            if special is None:
                self.position=len(self.buffer)
                if self.eof:raise ValueError('Packet字符串未结束')
                self.fill();continue
            char=special.group();self.position=special.end()
            if char=='"':return
            if char!='\\':raise ValueError('Packet字符串包含未转义控制字符')
            escape=self.raw()
            if not escape or escape not in '"\\/bfnrtu':raise ValueError('Packet字符串转义无效')
            self.position+=1
            if escape=='u':
                for unused in range(4):
                    digit=self.raw()
                    if not digit or digit not in '0123456789abcdefABCDEF':raise ValueError('Packet Unicode转义无效')
                    self.position+=1

    def digits(self):
        count=0
        while True:
            self.raw();match=_DIGITS.match(self.buffer,self.position)
            if not match:break
            count+=match.end()-self.position;self.position=match.end()
            if self.position<len(self.buffer) or self.eof:break
        return count

    def literal(self,value):
        for expected in value:
            if self.raw()!=expected:raise ValueError('Packet JSON字面量无效')
            self.position+=1

    def discard(self):
        token=self.peek()
        if token=='{':
            self.take('{')
            if self.peek()!='}':
                while True:
                    if self.peek()!='"':raise ValueError('Packet对象键无效')
                    self.string();self.take(':');self.discard()
                    if self.peek()=='}':break
                    self.take(',')
            self.take('}')
        elif token=='[':
            self.take('[')
            if self.peek()!=']':
                while True:
                    self.discard()
                    if self.peek()==']':break
                    self.take(',')
            self.take(']')
        elif token=='"':self.string()
        else:
            negative=token=='-'
            if negative:self.position+=1;token=self.raw()
            constants={'t':'true','f':'false','n':'null','N':'NaN','I':'Infinity'}
            if token in constants:
                if negative and token!='I':raise ValueError('Packet JSON数字无效')
                self.literal(constants[token])
            else:
                if token=='0':self.position+=1
                elif token and token in '123456789':self.digits()
                else:raise ValueError('Packet JSON值无效')
                if self.raw()=='.':
                    self.position+=1
                    if not self.digits():raise ValueError('Packet小数无效')
                if self.raw() and self.raw() in 'eE':
                    self.position+=1
                    if self.raw() and self.raw() in '+-':self.position+=1
                    if not self.digits():raise ValueError('Packet指数无效')
            if self.raw() and self.raw() not in ' \t\r\n,]}':raise ValueError('Packet JSON标量边界无效')

    def object_fields(self,fields):
        self.take('{');result={}
        if self.peek()!='}':
            while True:
                if self.peek()!='"':raise ValueError('Packet对象键无效')
                key=self.value()
                if not isinstance(key,str):raise ValueError('Packet对象键无效')
                self.take(':')
                if key in fields:result[key]=self.value()
                else:self.discard()
                if self.peek()=='}':break
                self.take(',')
        self.take('}');return result

    def packet(self,identifiers):
        self.take('{');result={}
        if self.peek()!='}':
            while True:
                if self.peek()!='"':raise ValueError('Packet对象键无效')
                key=self.value()
                if not isinstance(key,str):raise ValueError('Packet对象键无效')
                self.take(':')
                if key in {'concurrency_hints','nvic_priorities'}:result[key]=self.value()
                elif identifiers and key=='variable':
                    result[key]=self.object_fields({'name','qualified_name','canonical_path'}) if self.peek()=='{' else self.value()
                elif identifiers and key=='functions':
                    self.take('[');names=[];seen=set()
                    if self.peek()!=']':
                        while True:
                            item=self.object_fields({'name'});name=item.get('name')
                            if name and name not in seen:names.append(item);seen.add(name)
                            if self.peek()==']':break
                            self.take(',')
                    self.take(']');result[key]=names
                else:self.discard()
                if self.peek()=='}':break
                self.take(',')
        self.take('}')
        if self.peek():raise ValueError('Packet JSON末尾存在额外内容')
        return result


def validation_packet(path,*,identifiers=False):
    from .shared_json import encoded_stream
    with path.open(encoding='utf-8-sig') as stream:
        if encoded_stream(stream):
            # Historical shared-codec Packets retain their old decoder. New
            # canonical Packets are ordinary JSON; this is not a bounded claim
            # for unverified historical codecs.
            from .common import read_json
            return read_json(path)
        reader=ReceiptReader(stream)
        if reader.peek()!='{':
            from .common import read_json
            return read_json(path)
        return reader.packet(identifiers)
