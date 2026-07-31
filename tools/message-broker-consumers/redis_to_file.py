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
Redis to JSON Lines Dumper
Reads messages from Redis streams and dumps them to JSON lines txt files
"""

import argparse
import logging
import os

import redis

from base_consumer import (
    BATCH_SIZE,
    BaseMessageConsumer,
    DEFAULT_POLL_TIMEOUT_SECONDS,
    non_negative_float_arg,
    non_negative_int_arg,
    positive_float_arg,
    parse_source_names,
)

# Redis-specific constants
DEFAULT_REDIS_HOST = 'localhost'
DEFAULT_REDIS_PORT = 6379

logger = logging.getLogger(__name__)


class RedisMessageConsumer(BaseMessageConsumer):
    """Redis-specific implementation of the message consumer"""
    
    def get_consumer_type(self):
        """Return the type of consumer"""
        return "Redis"
    
    def get_source_names(self):
        """Get list of streams from args"""
        return parse_source_names(self.args.streams, 'Redis stream')
    
    def create_connection(self, source_name, consumer_group, **kwargs):
        """Create Redis connection and ensure consumer group exists"""
        redis_host = kwargs.get('redis_host', self.args.redis_host)
        redis_port = kwargs.get('redis_port', self.args.redis_port)
        
        # Connect to Redis
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=False  # Keep as bytes for protobuf
        )
        
        # Ensure consumer group exists
        try:
            redis_client.xgroup_create(source_name, consumer_group, mkstream=True)
            logger.info(f"[{source_name}] Created consumer group '{consumer_group}'")
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise RuntimeError(f"Failed to create consumer group '{consumer_group}' for stream '{source_name}'") from e
        
        return redis_client
    
    def consume_messages(self, connection, source_name, consumer_group, **kwargs):
        """Consume messages from Redis stream"""
        # Generate a unique consumer name for this process
        consumer_name = f"consumer-{source_name}-{os.getpid()}"
        
        max_messages = kwargs.get('max_messages')
        batch_size = min(BATCH_SIZE, max_messages) if max_messages else BATCH_SIZE
        poll_timeout = kwargs.get('poll_timeout_seconds', DEFAULT_POLL_TIMEOUT_SECONDS)

        # Read messages from Redis
        messages = connection.xreadgroup(
            consumer_group,
            consumer_name,
            {source_name: '>'},
            count=batch_size,
            block=max(1, int(poll_timeout * 1000))
        )
        
        if not messages:
            return  # No messages available
        
        # Process messages
        for _, stream_messages in messages:
            for msg_id, data in stream_messages:
                # Extract the message from Redis body
                # Typically Redis stream mdx data has a "value" field containing the actual data
                if b'value' in data:
                    yield (msg_id, data[b'value'])
    
    def acknowledge_messages(self, connection, source_name, consumer_group, message_ids):
        """Acknowledge processed messages in Redis"""
        if message_ids:
            connection.xack(source_name, consumer_group, *message_ids)
    
    def close_connection(self, connection):
        """Close the Redis connection"""
        connection.close()
    
    def get_connection_info(self):
        """Get Redis connection info for logging"""
        return f"{self.args.redis_host}:{self.args.redis_port}"
    
    def get_process_args(self, source_name):
        """Get process arguments for a Redis stream"""
        # Create output file path for this stream
        output_file_path = os.path.join(self.args.output_dir, f"{source_name}.txt")
        
        return {
            'output_file_path': output_file_path,
            'connection_params': {
                'redis_host': self.args.redis_host,
                'redis_port': self.args.redis_port
            }
        }


def main(args):
    """Main function to run the Redis consumer"""
    consumer = RedisMessageConsumer(args)
    return consumer.run()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Dump Redis streams to JSON lines files')
    parser.add_argument('--streams', default='mdx-raw',
                        help='Comma-separated list of Redis streams (default: mdx-raw)')
    parser.add_argument('--output-dir', default='redis_dumps',
                        help='Output directory for JSON lines files (default: redis_dumps)')
    parser.add_argument('--redis-host', default=DEFAULT_REDIS_HOST,
                        help=f'Redis host (default: {DEFAULT_REDIS_HOST})')
    parser.add_argument('--redis-port', type=int, default=DEFAULT_REDIS_PORT,
                        help=f'Redis port (default: {DEFAULT_REDIS_PORT})')
    parser.add_argument('--consumer-group', default='redis-json-dumper',
                        help='Redis consumer group name (default: redis-json-dumper)')
    parser.add_argument('--max-messages', type=non_negative_int_arg, default=0,
                        help='Maximum messages to read per stream; 0 means unlimited (default: 0)')
    parser.add_argument('--timeout-seconds', type=non_negative_float_arg, default=0.0,
                        help='Maximum runtime per stream; 0 means unlimited (default: 0)')
    parser.add_argument('--poll-timeout-seconds', type=positive_float_arg,
                        default=DEFAULT_POLL_TIMEOUT_SECONDS,
                        help=f'Maximum Redis blocking-read wait (default: {DEFAULT_POLL_TIMEOUT_SECONDS:g})')
    
    args = parser.parse_args()
    raise SystemExit(0 if main(args) else 1)
