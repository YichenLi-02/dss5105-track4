"""Build answer-free inputs or score human-reviewed multi-label mail triage.

Standard library only. Does not contact a model, mailbox, calendar or network.
Example:
  python prepare_eval.py make-inputs --split holdout --out eval_inputs.jsonl
  python prepare_eval.py score --reference reviewed.jsonl --predictions predictions.jsonl --split holdout
"""
import argparse,json,sys
from pathlib import Path

def read_jsonl(path):
    with Path(path).open(encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]

def inputs(rows, split):
    for r in rows:
        if r['split']!=split or r['direction']!='inbound': continue
        yield {'sample_id':r['sample_id'],'input':{
            'user_request':'按收到这封邮件时的可见内容分类，保留不确定性；不执行操作。',
            'reference_datetime':r['message_datetime_original'],'user_timezone':None,
            'message':{'source_id':r['sample_id'],'direction':r['direction'],
                'sent_at':r['message_datetime_original'],'subject':r['subject'],
                'body':r['body_redacted'],'attachments_metadata':r['attachments_present']},
            'thread_context_before_reference':[],
            'preferences':{'opted_in_opportunities':[]}}}

def score(reference, predictions, split):
    refs=[r for r in reference if r['split']==split and r['direction']=='inbound']
    if not refs: raise ValueError('No reference messages for this split')
    if any(r['annotation'].get('status')!='human_reviewed' or not r['annotation'].get('reviewed_by') for r in refs):
        raise ValueError('Reference is not independently human reviewed. Set annotation.status=human_reviewed and reviewed_by after checking/correcting each label. Do not auto-approve.')
    p={}
    for r in predictions:
        key=r.get('source_id',r.get('sample_id'))
        if key in p: raise ValueError('Duplicate prediction ID: '+str(key))
        p[key]=r
    reference_ids={r['sample_id'] for r in refs}
    if set(p)!=reference_ids:
        raise ValueError('Prediction IDs must exactly match selected split. Missing='+str(sorted(reference_ids-set(p)))+'; extra='+str(sorted(set(p)-reference_ids)))
    counts={k:dict(TP=0,FP=0,FN=0,TN=0) for k in ['needs_reply','needs_action']}; exact=0
    for r in refs:
        labels=p[r['sample_id']].get('labels',{})
        if any(type(labels.get(k)) is not bool for k in ['needs_reply','needs_action','ignore']):
            raise ValueError('Predicted labels must be JSON booleans for '+r['sample_id'])
        if labels['ignore']!=(not(labels['needs_reply'] or labels['needs_action'])):
            raise ValueError('Inconsistent ignore for '+r['sample_id'])
        correct=True
        for key in counts:
            truth=r['annotation'][key]
            if type(truth) is not bool: raise ValueError('Human reference label must be boolean')
            pred=labels[key]; counts[key][('T' if pred==truth else 'F')+('P' if pred else 'N')]+=1
            correct &= pred==truth
        exact+=int(correct)
    metrics={}
    for key,c in counts.items():
        tp,fp,fn=c['TP'],c['FP'],c['FN']
        metrics[key]={'confusion_matrix':c,'precision':tp/(tp+fp) if tp+fp else None,
                      'recall':tp/(tp+fn) if tp+fn else None,
                      'f1':2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else None,
                      'positive_reference_count':tp+fn}
    return {'message_count':len(refs),'split':split,'reference_status':'human_reviewed',
            'exact_match_count':exact,'exact_match_rate':exact/len(refs),'metrics':metrics,
            'scope':'triage only; does not evaluate dates, tone, planning or actual tool approval enforcement'}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('make-inputs'); a.add_argument('--source',default=str(Path(__file__).with_name('selected_50.jsonl'))); a.add_argument('--split',choices=['dev','holdout'],default='holdout'); a.add_argument('--out',required=True)
    b=sub.add_parser('score'); b.add_argument('--reference',required=True); b.add_argument('--predictions',required=True); b.add_argument('--split',choices=['dev','holdout'],default='holdout')
    args=p.parse_args()
    if args.cmd=='make-inputs':
        rows=list(inputs(read_jsonl(args.source),args.split))
        with Path(args.out).open('x',encoding='utf-8') as f:
            for r in rows: f.write(json.dumps(r,ensure_ascii=False)+'\n')
        print(json.dumps({'inputs_written':len(rows),'contains_annotations':False,'network_calls':0}))
    else: print(json.dumps(score(read_jsonl(args.reference),read_jsonl(args.predictions),args.split),ensure_ascii=False,indent=2))

if __name__=='__main__':
    try: main()
    except (ValueError,KeyError,FileExistsError) as exc:
        print(str(exc),file=sys.stderr); sys.exit(2)
