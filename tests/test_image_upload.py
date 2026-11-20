import io
import json
from pathlib import Path

import pytest
from PIL import Image

from arisekit.benchmark import Benchmark
from arisekit.client import ModelResponse
from arisekit.images.image_upload import freeze_upload, advance_upload, run_upload, upload_report, upload_status
from arisekit.images.imaging import read_json


def setup(root, **changes):
    assets = {}
    for index in range(2):
        stream = io.BytesIO();Image.new('RGB',(12,12),(index * 100,0,0)).save(stream,format='PNG')
        assets[f'private-filename-{index}.png']=stream.getvalue()
    brief={'field':'diagnostic radiology','modality':'mixed','criteria':'Distinct visual decisions',
        'tasks_per_image':2,'generator_model':'writer','critic_model':'critic','models':['solver'],
        'max_calls':10,'max_cost':1,'max_cost_per_call':.025,**changes}
    evidence={name:{'labels':[{'task':f'Feature {i} presence','choices':['yes','no'],'answer':'yes',
        'provenance':{'kind':'dataset-annotation','source':'Synthetic engineering annotation'}}for i in range(2)]}for name in assets}
    return freeze_upload(root,assets,brief=brief,evidence=evidence,
        authorization={'authorized':True,'provider_permission':True,'data_class':'synthetic','scope':'Engineering fixture'},
        source={'name':'Generated engineering pixels','revision':'1','license':'Fixture'})


class Client:
    def __init__(self,model,calls,*,failure=None):self.model,self.calls,self.failure=model,calls,failure
    def __call__(self,call):
        step=call.item.metadata['image_step'];self.calls.append((self.model,call))
        assert call.item.attachments and call.item.ground_truth is None
        assert 'private-filename'not in call.item.prompt
        if step.startswith('generate:'):
            assert len(json.loads(call.item.prompt)['supplied_evidence']['labels'])==2
            text=json.dumps({'tasks':[{'question':f'Is feature {i} visible?','answer':'yes',
                'choices':['yes','no'],'reference_id':f'label-{i+1}','question_type':'presence','evidence':'Fixture pixels','uncertainty':'Synthetic'}for i in range(2)]})
        elif step.startswith('reference:'):
            assert set(json.loads(call.item.prompt))=={'question','choices','supplied_evidence'}
            assert all('answer'not in label for label in json.loads(call.item.prompt)['supplied_evidence']['labels'])
            assert 'Fixture pixels'not in call.item.prompt
            if self.failure=='timeout':raise TimeoutError('fixture timeout')
            text=json.dumps({'answer':'no','evidence':'Independent fixture view','uncertainty':'Synthetic','issues':['Disagrees']})
        else:text='yes'
        return ModelResponse(text=text,cost=.001,response_id='fixture-'+str(len(self.calls)),
            cost_known=not(step.startswith('reference:')and self.failure=='unknown-cost'))


def execute(root,calls,**kw):
    return run_upload(root,generator=Client('writer',calls),critic=Client('critic',calls,**kw),
        solvers={'solver':Client('solver',calls)})


def test_images_without_annotations_become_runnable_benchmark(tmp_path):
    root=tmp_path/'upload';setup(root);calls=[]
    assert execute(root,calls)['status']=='complete' and len(calls)==10
    report=upload_report(root)
    assert report['generated_tasks']==report['reviewed_tasks']==4
    assert report['independent_reference_agreements']==0
    assert report['expert_ratings_completed']==0 and report['reference_kind']=='supplied-labels-or-ai-report-interpretation'
    assert report['models'][0]['correct']==4
    source=read_json(root/'source/source.json')
    assert all(t['answer']=='yes'and t['provenance']['kind']=='dataset-annotation'and t['provenance']['independent_answer']=='no'
        for r in source['records']for t in r['targets'])
    benchmark=Benchmark.from_package(root/'benchmark')
    assert len(benchmark.dataset)==4
    assert execute(root,calls)['status']=='complete' and len(calls)==10


@pytest.mark.parametrize('failure',['timeout','unknown-cost'])
def test_unknown_reference_attempt_is_retained_without_replay(tmp_path,failure):
    root=tmp_path/'upload';setup(root);calls=[]
    assert execute(root,calls,failure=failure)['status']=='stopped'
    count=len(calls)
    assert execute(root,calls,failure=failure)['status']=='stopped' and len(calls)==count
    advance_upload(root,generator=Client('writer',calls),critic=Client('critic',calls),solvers={'solver':Client('solver',calls)})
    assert len(calls)==count and not(root/'benchmark').exists()


def test_plan_or_pixels_cannot_change_after_freeze(tmp_path):
    root=tmp_path/'upload';setup(root)
    plan=read_json(root/'upload-plan.json');(root/plan['images'][0]['image']).write_bytes(b'bad')
    with pytest.raises(ValueError):upload_status(root)


def test_budget_covers_assigned_work_before_generation(tmp_path):
    with pytest.raises(ValueError,match='needs 10 calls'):setup(tmp_path/'upload',max_calls=9)
    assert not(tmp_path/'upload').exists()


def test_missing_evidence_is_rejected_before_any_generation(tmp_path):
    with pytest.raises(ValueError,match='requires supplied labels or a report'):
        freeze_upload(tmp_path/'upload',{'a.png':b'a','b.png':b'b'},brief={
            'field':'radiology','modality':'mixed','criteria':'visual tasks','tasks_per_image':1,
            'generator_model':'writer','critic_model':'critic','models':[],
            'max_calls':10,'max_cost':1,'max_cost_per_call':.025},
            authorization={'authorized':True,'provider_permission':True,'data_class':'synthetic','scope':'fixture'},
            source={'name':'fixture','revision':'1','license':'fixture'},evidence={})
    assert not(tmp_path/'upload').exists()


def test_writer_cannot_change_a_supplied_label(tmp_path):
    root=tmp_path/'upload';setup(root);calls=[]
    class ChangedAnswer(Client):
        def __call__(self,call):
            response=super().__call__(call)
            if call.item.metadata['image_step'].startswith('generate:'):
                value=json.loads(response.text);value['tasks'][0]['answer']='no';response.text=json.dumps(value)
            return response
    result=run_upload(root,generator=ChangedAnswer('writer',calls),critic=Client('critic',calls),solvers={'solver':Client('solver',calls)})
    assert result['status']=='stopped'and 'cannot change supplied label'in result['error']
    assert len(calls)==1 and not(root/'benchmark').exists()


def test_report_answers_remain_ai_interpretations_with_exact_source_excerpt(tmp_path):
    original=tmp_path/'setup';setup(original)
    plan=read_json(original/'upload-plan.json')
    assets={f'image-{i}.png':(original/r['image']).read_bytes()for i,r in enumerate(plan['images'])}
    report_text='Feature 0 is visible. Feature 1 is absent.'
    evidence={name:{'report':{'text':report_text,'provenance':{'kind':'dataset-annotation','source':'Synthetic report fixture'}}}for name in assets}
    root=tmp_path/'report';freeze_upload(root,assets,brief=plan['brief'],evidence=evidence,
        authorization=plan['authorization'],source=plan['source'])
    calls=[]
    class ReportClient:
        def __init__(self,model):self.model=model
        def __call__(self,call):
            calls.append(call);step=call.item.metadata['image_step']
            if step.startswith('generate:'):
                assert json.loads(call.item.prompt)['supplied_evidence']['report']['text']==report_text
                text=json.dumps({'tasks':[{'question':f'Is feature {i} visible?','answer':'yes'if i==0 else'no',
                    'choices':['yes','no'],'reference_id':'report','question_type':'presence',
                    'evidence':f'Feature {i} is '+('visible.'if i==0 else'absent.'),'uncertainty':'Fixture'}for i in range(2)]})
            elif step.startswith('reference:'):
                text=json.dumps({'answer':'yes','evidence':'Fixture','uncertainty':'Fixture','issues':[]})
            else:text='yes'
            return ModelResponse(text=text,cost=.001,response_id=f'fixture-{len(calls)}')
    assert run_upload(root,generator=ReportClient('writer'),critic=ReportClient('critic'),solvers={'solver':ReportClient('solver')})['status']=='complete'
    source=read_json(root/'source/source.json')
    assert all(t['provenance']['kind']=='ai'and t['provenance']['upstream_reference_kind']=='dataset-annotation'
        and t['provenance']['supporting_excerpt']in report_text for r in source['records']for t in r['targets'])
