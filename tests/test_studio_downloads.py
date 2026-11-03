from contextlib import ExitStack
from pathlib import Path
import tempfile
import unittest

from fastapi.testclient import TestClient

from ecra.studio.downloads import DownloadExpired,DownloadTickets
from ecra.studio.server import create_app


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='ECRA 下载凭证 ');self.addCleanup(self.temp.cleanup)
        self.data=Path(self.temp.name)/'data';self.exports=self.data/'exports';self.exports.mkdir(parents=True)
        self.name='a'*32+'.ecra-report';self.file=self.exports/self.name;self.payload=b'actual transport bytes\x00\xff\n';self.file.write_bytes(self.payload)
        self.app=create_app(self.data,token='private-session-do-not-put-in-url',authority='127.0.0.1:12345')
        stack=ExitStack();self.addCleanup(stack.close)
        self.client=stack.enter_context(TestClient(self.app,base_url='http://127.0.0.1:12345',
            headers={'X-ECRA-Session':'private-session-do-not-put-in-url','Origin':'http://127.0.0.1:12345'}))

    def issue(self):
        response=self.client.post('/api/download/'+self.name+'/ticket')
        self.assertEqual(response.status_code,200,response.text);return response.json()['download']

    def test_real_native_transfer_needs_authenticated_issue_and_keeps_main_api_private(self):
        url='/api/download/'+self.name+'/ticket'
        self.assertEqual(self.client.post(url,headers={'X-ECRA-Session':''}).status_code,401)
        self.assertEqual(self.client.post(url,headers={'Origin':'http://evil.invalid'}).status_code,403)
        grant=self.issue();self.assertNotIn('private-session',grant)
        response=self.client.get(grant,headers={'X-ECRA-Session':''})
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,self.payload)
        self.assertIn('attachment',response.headers['content-disposition']);self.assertIn(self.name,response.headers['content-disposition'])
        self.assertEqual(response.headers['cache-control'],'no-store');self.assertEqual(response.headers['referrer-policy'],'no-referrer')
        self.assertEqual(self.client.get('/api/download/'+self.name,headers={'X-ECRA-Session':''}).status_code,401)
        self.assertEqual(self.client.get('/api/bootstrap',headers={'X-ECRA-Session':grant}).status_code,401)
        self.assertEqual(self.client.get(grant,headers={'Origin':'http://evil.invalid'}).status_code,403)
        self.assertEqual(self.client.get(grant,headers={'Host':'evil.invalid'}).status_code,403)
        self.assertEqual(self.file.read_bytes(),self.payload)

    def test_real_range_retry_and_authenticated_header_download_remain_compatible(self):
        grant=self.issue();first=self.client.get(grant,headers={'Range':'bytes=0-5','X-ECRA-Session':''})
        second=self.client.get(grant,headers={'Range':'bytes=6-','X-ECRA-Session':''})
        self.assertEqual(first.status_code,206,first.text);self.assertEqual(second.status_code,206,second.text)
        self.assertEqual(first.content+second.content,self.payload)
        self.assertEqual(self.client.get('/api/download/'+self.name).content,self.payload)
        self.assertEqual(self.issue(),grant)

    def test_expired_missing_changed_and_malformed_grants_never_reveal_other_files(self):
        now=[0.0];self.app.state.download_tickets.clock=lambda:now[0]
        grant=self.issue();now[0]=901
        self.assertEqual(self.client.get(grant).status_code,410)
        grant=self.issue();self.file.write_bytes(b'replaced owned transport fixture')
        self.assertEqual(self.client.get(grant).status_code,410)
        self.assertEqual(self.client.get('/export-download/not-a-ticket').status_code,410)
        self.assertEqual(self.client.post('/api/download/not-a-file/ticket').status_code,400)
        grant=self.issue();self.file.unlink()
        self.assertEqual(self.client.get(grant).status_code,410)

    def test_registry_is_bounded_and_expired_grants_do_not_consume_slots(self):
        now=[0.0];tickets=DownloadTickets(self.exports,clock=lambda:now[0],lifetime=10,maximum=2)
        names=[character*32+'.ecra-report' for character in 'abc']
        for name in names:(self.exports/name).write_bytes(b'owned transport fixture')
        grants=[tickets.issue(name) for name in names[:2]]
        self.assertEqual(tickets.issue(names[0])['download'],grants[0]['download'])
        with self.assertRaises(ValueError):tickets.issue(names[2])
        now[0]=11
        with self.assertRaises(DownloadExpired):tickets.resolve(grants[0]['download'].split('/')[-1])
        self.assertEqual(tickets.issue(names[2])['filename'],names[2]);self.assertEqual(len(tickets.grants),1)


if __name__=='__main__':unittest.main()
