# RT-VLM Kafka and Redis error-publication runtime successor

This package binds official capability 365 to current-Thor runtime evidence. It
proves both production branches of RT-VLM error publication: Kafka is the
default backend, while the supported runtime switch routes the same JSON schema
to Redis Pub/Sub.

The default command is inert. Acknowledged execution creates one randomly named,
owned Kafka topic and one ephemeral Redis subscription, invokes the production
`RTVIStreamHandler` publication method once per backend, validates both messages,
and removes all owned state. It makes no HTTP, model, Agent, asset, stream, or
service-lifecycle request.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 execute.py plan
PYTHONDONTWRITEBYTECODE=1 python3 execute.py execute \
  --ack I_ACK_ONE_OWNED_KAFKA_TOPIC_AND_EPHEMERAL_REDIS_ERROR_PROOF
```
