"""Research must resume safely, throttle persistently, and never guess wiring."""
import argparse
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from devtools.battery_pinout_search import (
    Queue, classify_page, due_time, eligible_models, google_host, identity_key,
    make_result, query_for, resolve, run, save_json, unpack_result_url, worker_lock,
)


def entry(brand, model, pins=None, kind="model"):
    return {"id":identity_key(brand, model), "manufacturer":brand, "model":model,
            "pins":[] if pins is None else pins, "identity_kind":kind}


def page_for(job, results=None):
    return {"url":"https://www.google.com/search?" + urlencode({"q":job["query"]}),
            "text":"Search Results", "results":results if results is not None else [{"title":job['model']+' pinout',
                "url":"https://example.com/battery", "snippet":"Exact model connector diagram"}]}


def arguments(**changes):
    data=dict(min_interval=90, max_interval=150, daily_limit=500, batch_size=20,
              batch_pause=600, headless=True, max_jobs=1, verification_timeout=0)
    data.update(changes)
    return argparse.Namespace(**data)


class ResearchQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue=Queue(Path(self.temp.name))
        self.addCleanup(self.queue.close)

    def test_only_unwired_known_brand_identities_are_scheduled_and_brands_interleave(self):
        records=[entry('Lenovo','L22D2PG2'),entry('Lenovo','L20M3PC2'),entry('HP','HS04'),
                 entry('Asus','C21N1818-1'),entry('Unspecified','BTP-D4BM'),
                 entry('Acer','AC14B8K',[{'role':'data'}]),entry('HP','HS04')]
        chosen=eligible_models(records,first=['L22D2PG2'])
        self.assertEqual(chosen[0]['model'],'L22D2PG2')
        self.assertEqual(len(chosen),4)
        self.assertEqual({e['manufacturer'] for e in chosen},{'HP','Lenovo','Asus'})
        self.assertEqual(query_for('Lenovo','L22D2PG2'),'Lenovo "L22D2PG2" battery pinout')

    def test_completed_queries_survive_reinitialization_and_cannot_become_pinouts(self):
        self.queue.initialize([entry('Lenovo','L22D2PG2')])
        job=self.queue.next_job()
        self.queue.begin(job,time.time())
        snapshot=page_for(job)
        snapshot['text']='AI Overview\nUse this generic 8-pin connector\nWeb results\nOther pages'
        result=make_result(snapshot,job)
        self.assertFalse(result['verified_pinout'])
        self.assertNotIn('pins',result)
        self.assertTrue(result['ai_overview_hint'])
        self.queue.finish(job,result,time.time())
        self.queue.initialize([entry('Lenovo','L22D2PG2')])
        self.assertIsNone(self.queue.next_job())
        self.assertEqual(self.queue.snapshot()['states'],{'searched':1})
        self.assertEqual(self.queue.snapshot()['verified_pinouts_imported'],0)

    def test_crash_recovery_reuses_completed_cache_without_another_request(self):
        self.queue.initialize([entry('HP','HS04')])
        job=self.queue.next_job();self.queue.begin(job,time.time())
        save_json(self.queue.directory/'results'/(job['id']+'.json'),make_result(page_for(job),job))
        self.queue.recover()
        self.assertIsNone(self.queue.next_job())
        self.assertEqual(len(self.queue.request_times(time.time())),1)

    def test_rate_limit_and_restart_keep_the_reserved_time_and_daily_budget(self):
        now=100000.0
        self.queue.initialize([entry('HP','HS04')]);job=self.queue.next_job()
        self.queue.begin(job,now-60)
        self.queue.begin(job,now-30)
        self.queue.set('next_request_at',now+90)
        self.assertEqual(due_time(self.queue,now,500),now+90)
        self.assertEqual(due_time(self.queue,now,2),now-60+86400+1)
        self.queue.fail(job,'rate_limited','429',{'url':'https://www.google.com/search'})
        self.assertEqual(self.queue.get('paused')['reason'],'rate_limited')
        self.assertGreaterEqual(self.queue.get('next_request_at'),time.time()+3590)

    def test_single_worker_lock_rejects_a_second_process_handle(self):
        with worker_lock(self.queue.directory):
            with self.assertRaises(RuntimeError):
                with worker_lock(self.queue.directory):
                    self.fail('second worker lock was granted')

    def test_captcha_pauses_the_first_job_and_restarting_sends_nothing_more(self):
        self.queue.initialize([entry('HP','HS04'),entry('Lenovo','L22D2PG2')])
        calls=[]
        class Browser:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            @property
            def page(self):return self
            def screenshot(self,**kwargs):pass
            def search(self,job):
                calls.append(job['id'])
                return 'needs_verification',{'url':'https://www.google.com/sorry/index'}
        with patch('devtools.battery_pinout_search.GoogleBrowser',Browser):
            self.assertEqual(run(self.queue,arguments()),3)
            self.assertEqual(run(self.queue,arguments()),3)
        self.assertEqual(len(calls),1)
        self.assertEqual(self.queue.snapshot()['states'],{'pending':2})
        self.assertEqual(self.queue.get('worker_state'),'paused')

    def test_success_saves_results_and_a_future_slot_without_filling_any_connector(self):
        self.queue.initialize([entry('HP','HS04')])
        class Browser:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def search(self,job):return 'searched',page_for(job)
            def resolve_leads(self,result):return None
        with patch('devtools.battery_pinout_search.GoogleBrowser',Browser):
            self.assertEqual(run(self.queue,arguments()),0)
        self.assertEqual(self.queue.snapshot()['states'],{'searched':1})
        self.assertGreater(self.queue.get('next_request_at'),time.time()+85)
        self.assertEqual(self.queue.snapshot()['verified_pinouts_imported'],0)

    def test_configuration_cannot_accidentally_disable_throttling_or_job_limit(self):
        for args in (arguments(min_interval=0),arguments(daily_limit=0),arguments(max_jobs=0)):
            with self.assertRaises(ValueError):run(self.queue,args)

    def test_resume_cannot_clear_attention_while_another_worker_owns_the_queue(self):
        paused={'reason':'http_error','url':'https://www.google.com/search'}
        self.queue.set('paused',paused)
        with worker_lock(self.queue.directory):
            with self.assertRaises(RuntimeError):run(self.queue,arguments(),resume=True)
        self.assertEqual(self.queue.get('paused'),paused)

    def test_manual_resume_after_stop_clears_cancellation_before_verification(self):
        self.queue.initialize([entry('HP','HS04')]);job=self.queue.next_job()
        self.queue.begin(job,time.time())
        self.queue.fail(job,'needs_verification','Manual check',{'url':'https://www.google.com/sorry/index'})
        self.queue.set('stop_requested',True)
        class Browser:
            def __init__(self,*args,**kwargs):pass
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def verify(inner,job,url,**kwargs):
                self.assertFalse(kwargs['cancelled']())
                return page_for(job)
        with patch('devtools.battery_pinout_search.GoogleBrowser',Browser):
            self.assertEqual(resolve(self.queue,arguments(continue_after=False)),0)
        self.assertIsNone(self.queue.get('paused'))
        self.assertFalse(self.queue.get('stop_requested'))
        self.assertEqual(self.queue.snapshot()['states'],{'searched':1})


class SearchEvidenceTests(unittest.TestCase):
    def test_http_200_captcha_empty_dom_and_wrong_query_are_not_success(self):
        job={'model':'HS04','query':query_for('HP','HS04')}
        self.assertEqual(classify_page({'url':'https://www.google.com/sorry/index','text':''},job['query']),'needs_verification')
        self.assertEqual(classify_page(page_for(job),job['query'],429),'rate_limited')
        self.assertEqual(classify_page({'url':page_for(job)['url'],'text':'Loading','results':[]},job['query']),'unparsed_page')
        self.assertEqual(classify_page(page_for(job),'different battery'),'unexpected_page')
        self.assertEqual(classify_page({'url':page_for(job)['url'],'text':'did not match any documents','results':[]},job['query']),'searched')

    def test_google_tracking_is_not_mistaken_for_a_primary_source(self):
        self.assertEqual(unpack_result_url('https://www.google.com/goto?url=opaque'),'')
        self.assertEqual(unpack_result_url('https://www.google.com/url?'+urlencode({'q':'https://example.com/pinout'})),'https://example.com/pinout')
        self.assertEqual(unpack_result_url('javascript:alert(1)'),'')
        self.assertFalse(google_host('google.com.evil'))
        self.assertTrue(google_host('www.google.com'))

    def test_vietnamese_battery_word_and_retail_hits_are_not_wiring_evidence(self):
        job={'brand':'Lenovo','model':'L22D2PG2','catalog_id':'test','query':query_for('Lenovo','L22D2PG2')}
        snapshot=page_for(job,[{'title':'Pin laptop L22D2PG2','url':'https://shopee.vn/listing','snippet':'Replacement battery in stock'}])
        result=make_result(snapshot,job)
        self.assertEqual(result['technical_leads'],0)
        self.assertEqual(result['review_state'],'no_pinout_evidence')
        self.assertFalse(result['verified_pinout'])

    def test_numeric_ai_pin_hint_is_kept_for_review_without_becoming_a_pinout(self):
        job={'brand':'Asus','model':'C21N1818-1','catalog_id':'test','query':query_for('Asus','C21N1818-1')}
        snapshot=page_for(job,[])
        snapshot['text']='AI Overview\nData on Pin 4, Clock on Pin 5\nWeb results\nStores only'
        snapshot['citations']=[{'title':'Manufacturer reference','url':'https://example.com/reference'}]
        result=make_result(snapshot,job)
        self.assertTrue(result['ai_mapping_hint'])
        self.assertEqual(result['review_state'],'ai_hint_unverified')
        self.assertEqual(result['ai_citations'][0]['url'],'https://example.com/reference')
        self.assertFalse(result['ai_citations'][0]['verified_source'])
        self.assertFalse(result['verified_pinout'])


if __name__=='__main__':unittest.main()
