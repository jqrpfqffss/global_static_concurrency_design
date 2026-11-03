"""Bounded, expiring capabilities for native browser file transfers.

Tickets reveal no Studio session credential and only authorize one existing
export identity. Range/retry requests remain possible until expiry; the main
API still requires its session header and same-origin write check.
"""
from dataclasses import dataclass
from pathlib import Path
import re
import secrets
import threading
import time

from ..workspace import no_links

EXPORT_NAME=re.compile(r'[a-f0-9]{32}\.ecra-(?:report|review-delta)')
TICKET=re.compile(r'[A-Za-z0-9_-]{43}')


class DownloadExpired(ValueError):pass


@dataclass(frozen=True)
class Grant:
    path:Path
    identity:tuple
    expires:float


class DownloadTickets:
    def __init__(self,exports,*,clock=time.monotonic,lifetime=900,maximum=128):
        self.exports=no_links(exports);self.clock=clock;self.lifetime=lifetime;self.maximum=maximum
        self.lock=threading.Lock();self.grants={}

    def path(self,name):
        if not isinstance(name,str) or not EXPORT_NAME.fullmatch(name):raise ValueError('导出文件身份无效')
        path=no_links(self.exports/name)
        if not path.is_file():raise ValueError('导出包不存在；原扫描仍保留，请重新导出')
        return path

    @staticmethod
    def identity(path):
        stat=path.stat()
        return stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns

    def prune(self,now):
        for key in [key for key,value in self.grants.items() if value.expires<=now]:del self.grants[key]

    def issue(self,name):
        path=self.path(name);identity=self.identity(path)
        with self.lock:
            now=self.clock();self.prune(now)
            # Reusing a still valid link does not accumulate grants for the
            # same immutable file. Authenticated requests renew its expiry.
            for ticket,grant in self.grants.items():
                if grant.path==path and grant.identity==identity:break
            else:
                if len(self.grants)>=self.maximum:raise ValueError('下载链接较多，请等待现有下载结束或链接到期后重试；导出包仍保留')
                ticket=secrets.token_urlsafe(32)
                while ticket in self.grants:ticket=secrets.token_urlsafe(32)
            self.grants[ticket]=Grant(path,identity,now+self.lifetime)
        return dict(download='/export-download/'+ticket,filename=name,expires_in_seconds=self.lifetime)

    def resolve(self,ticket):
        error='下载链接已过期或导出文件已变化；请从软件重新发起下载，原扫描和人工记录仍保留。'
        if not isinstance(ticket,str) or not TICKET.fullmatch(ticket):raise DownloadExpired(error)
        with self.lock:
            self.prune(self.clock());grant=self.grants.get(ticket)
            if grant is None:raise DownloadExpired(error)
            try:
                path=self.path(grant.path.name)
                if path!=grant.path or self.identity(path)!=grant.identity:raise ValueError('changed')
            except (OSError,ValueError) as exc:
                del self.grants[ticket];raise DownloadExpired(error) from exc
            return path
