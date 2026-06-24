Run a vulnerability blast radius scan on a package before patching.

Preferred: cerebrofy_vuln(package="<pkg>")
With specific function: cerebrofy_vuln(package="<pkg>", function_pattern="<pkg>.get")
With memories: cerebrofy_vuln(package="<pkg>", write_memories=true)

Decision rules:
- critical_exposure non-empty → patch entry_point neurons BEFORE upgrading the package
- is_trust_boundary true on a direct caller → external input reaches the vulnerable call, highest risk
- is_test true on all callers → low real-world risk, safe to upgrade without call-site changes
- pinned_version present → compare manually against CVE advisory version ranges
