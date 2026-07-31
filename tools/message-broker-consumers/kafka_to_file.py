#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Kafka to JSON Lines Dumper
Reads messages from Kafka topics and dumps them to JSON lines txt files
"""

import argparse
import logging
import os

from confluent_kafka import Consumer, KafkaError

from base_consumer import (
    BaseMessageConsumer,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    non_negative_float_arg,
    non_negative_int_arg,
    positive_float_arg,
    parse_source_names,
)

# Kafka-specific constants
DEFAULT_KAFKA_BROKER = 'localhost:9092'
logger = logging.getLogger(__name__)


class KafkaMessageConsumer(BaseMessageConsumer):
    """Kafka-specific implementation of the message consumer"""
    
    def get_consumer_type(self):
        """Return the type of consumer"""
        return "Kafka"
    
    def get_source_names(self):
        """Get list of topics from args"""
        return parse_source_names(self.args.topics, 'Kafka topic')
    
    def create_connection(self, source_name, consumer_group, **kwargs):
        """Create Kafka consumer connection"""
        kafka_broker = kwargs.get('kafka_broker', self.args.kafka_broker)
        
        consumer_config = {
            'bootstrap.servers': kafka_broker,
            'group.id': consumer_group,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': False,
            'enable.auto.offset.store': False,
            'session.timeout.ms': 30000,
            'max.poll.interval.ms': 300000
        }
        
        consumer = Consumer(consumer_config)
        consumer.subscribe([source_name])
        return consumer
    
    def consume_messages(self, connection, source_name, consumer_group, **kwargs):
        """Consume messages from Kafka topic"""
        # Poll for a single message
        poll_timeout = kwargs.get('poll_timeout_seconds', DEFAULT_POLL_TIMEOUT_SECONDS)
        msg = connection.poll(timeout=poll_timeout)
        
        if msg is None:
            return  # No messages available
        
        if msg.error():
            if msg.error().code() == KafkaError._PARTITION_EOF:
                # End of partition, not an error
                return
            else:
                logger.error(f"[{source_name}] Kafka error: {msg.error()}")
                # Return a special marker to indicate an error occurred
                # This will be counted in the stats but won't cause a sleep(5)
                yield ('__kafka_error__', None)
                return
        
        # Carry the message object as the acknowledgment handle. The base class
        # commits it only after decode, JSON write, and flush all succeed.
        yield (msg, msg.value())
    
    def acknowledge_messages(self, connection, source_name, consumer_group, message_ids):
        """Synchronously commit records after their output has been flushed."""
        for message in message_ids:
            connection.commit(message=message, asynchronous=False)
    
    def close_connection(self, connection):
        """Close the Kafka consumer"""
        connection.close()
    
    def get_connection_info(self):
        """Get Kafka broker info for logging"""
        return f"{self.args.kafka_broker}"
    
    def get_process_args(self, source_name):
        """Get process arguments for a Kafka topic"""
        # Create output file path for this topic
        output_file_path = os.path.join(self.args.output_dir, f"{source_name}.txt")
        
        return {
            'output_file_path': output_file_path,
            'connection_params': {
                'kafka_broker': self.args.kafka_broker
            }
        }


def main(args):
    """Main function to run the Kafka consumer"""
    consumer = KafkaMessageConsumer(args)
    return consumer.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Dump Kafka topics to JSON lines files')
    parser.add_argument('--topics', default='mdx-raw',
                        help='Comma-separated list of Kafka topics (default: mdx-raw)')
    parser.add_argument('--output-dir', default='kafka_dumps',
                        help='Output directory for JSON lines files (default: kafka_dumps)')
    parser.add_argument('--kafka-broker', default=DEFAULT_KAFKA_BROKER,
                        help=f'Kafka broker address (default: {DEFAULT_KAFKA_BROKER})')
    parser.add_argument('--consumer-group', default='kafka-json-dumper',
                        help='Kafka consumer group name (default: kafka-json-dumper)')
    parser.add_argument('--max-messages', type=non_negative_int_arg, default=0,
                        help='Maximum messages to read per topic; 0 means unlimited (default: 0)')
    parser.add_argument('--timeout-seconds', type=non_negative_float_arg, default=0.0,
                        help='Maximum runtime per topic; 0 means unlimited (default: 0)')
    parser.add_argument('--poll-timeout-seconds', type=positive_float_arg,
                        default=DEFAULT_POLL_TIMEOUT_SECONDS,
                        help=f'Maximum Kafka poll wait (default: {DEFAULT_POLL_TIMEOUT_SECONDS:g})')
    
    args = parser.parse_args()
    raise SystemExit(0 if main(args) else 1)
