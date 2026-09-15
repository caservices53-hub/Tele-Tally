from __future__ import annotations

import argparse
import json
import sys

from .job_engine import JobEngine


def pp(x):
    print(json.dumps(x,indent=2,ensure_ascii=False,default=str))


def main(argv=None):
    p=argparse.ArgumentParser(prog="gpt-tally",description="GPT-Tally Connect Pro V2 local bulk engine")
    sub=p.add_subparsers(dest="cmd",required=True)
    sub.add_parser("status")
    s=sub.add_parser("study"); s.add_argument("from_date"); s.add_argument("to_date")
    c=sub.add_parser("create-job"); c.add_argument("file"); c.add_argument("--sheet",default=""); c.add_argument("--company",default="")
    q=sub.add_parser("summary"); q.add_argument("job_id")
    e=sub.add_parser("exceptions"); e.add_argument("job_id")
    pv=sub.add_parser("preview"); pv.add_argument("job_id"); pv.add_argument("--limit",type=int,default=500)
    a=sub.add_parser("approve"); a.add_argument("job_id")
    t=sub.add_parser("teach"); t.add_argument("job_id"); t.add_argument("row_id",type=int); t.add_argument("entries_json"); t.add_argument("--party-ledger",default=""); t.add_argument("--bank-ledger",default="")
    po=sub.add_parser("post"); po.add_argument("job_id"); po.add_argument("--confirm-company",required=True)
    r=sub.add_parser("rules"); r.add_argument("company"); r.add_argument("--limit",type=int,default=100)
    args=p.parse_args(argv)
    eng=JobEngine()
    try:
        if args.cmd=="status": pp({"company":eng.gateway.ping(),"url":eng.settings.tally_url})
        elif args.cmd=="study": pp(eng.study_company(args.from_date,args.to_date))
        elif args.cmd=="create-job":
            jid=eng.create_job_from_file(args.file,args.sheet,args.company); pp(eng.summary(jid))
        elif args.cmd=="summary": pp(eng.summary(args.job_id))
        elif args.cmd=="exceptions": pp(eng.exceptions(args.job_id))
        elif args.cmd=="preview": pp(eng.preview(args.job_id,args.limit))
        elif args.cmd=="approve": pp(eng.approve(args.job_id))
        elif args.cmd=="teach": pp(eng.teach_row(args.job_id,args.row_id,json.loads(args.entries_json),args.party_ledger,args.bank_ledger))
        elif args.cmd=="post": pp(eng.post(args.job_id,args.confirm_company))
        elif args.cmd=="rules": pp(eng.learning.list_rules(args.company,args.limit))
        return 0
    except Exception as ex:
        print(f"ERROR: {ex}",file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
