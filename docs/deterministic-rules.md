# Deterministic rules

Rules execute before model enrichment and retain rule ID/version, source field, matched text, normalized value, and score contribution. Current defaults cover verified sender/domain vendor identity, canonical US jurisdictions, license phrases/numbers, explicit dates, requested-item lines, correspondence type, and routing.

Specific requested information beats generic renewal context. HTML is normalized with list and line boundaries; confidentiality tails are removed; quoted threads are separated. Introduction headings (`Please provide:`), deadline sentences, thanks, signatures, and quoted history are not requested items. Regex inputs are bounded by classification body settings; production registry rules must be reviewed and evaluated before activation.
