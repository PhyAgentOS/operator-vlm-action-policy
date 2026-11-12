# Security

This is a simulation-oriented action runtime, not a certified robot safety layer.
Use a trusted authenticated generic VLM service, restrict network access and keep
credentials in environment/service configuration. Model output remains untrusted
and is validated before commands are emitted. Preserve real robot interlocks,
controllers and independent safety supervision when developing hardware adapters.

No action is emitted after a policy failure. Workspace/joint checks are numerical
bounds, not collision checking. Legacy streams have documented synchronization
limitations. Do not expose control ports, model-service tokens or observations to
untrusted callers. Report suspected issues privately to repository maintainers;
never publish credentials or private scene/media data in an issue.
