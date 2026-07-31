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
Base Message Consumer Abstract Class
Provides common functionality for all message broker consumers (Kafka, Redis, MQTT, etc.)
"""

import json
import logging
import math
import os
import signal
import sys
import time
from abc import ABC, abstractmethod
from contextlib import suppress
from multiprocessing import Process

from google.protobuf.json_format import MessageToDict

import ext_pb2
import schema_pb2

# Default Constants
BATCH_SIZE = 100
DEFAULT_CONSUMER_GROUP = 'message-consumer'
DEFAULT_POLL_TIMEOUT_SECONDS = 1.0

# These mappings are intentionally limited to topic names and wire formats that
# are defined by this repository. Custom topic names need an explicit mapping;
# guessing a protobuf type can silently turn one valid wire format into another.
PROTOBUF_SOURCE_TYPES = {
    'mdx-raw': schema_pb2.Frame,
    'mdx-bev': schema_pb2.Frame,
    'mdx-frames': schema_pb2.Frame,
    'mdx-rtls': schema_pb2.Frame,
    'mdx-rtls-region-1': schema_pb2.Frame,
    'mdx-behavior': ext_pb2.Behavior,
    'mdx-events': ext_pb2.Behavior,
    'mdx-alerts': ext_pb2.Behavior,
    'mdx-behavior-plus': ext_pb2.Behavior,
    'mdx-vlm-alerts': ext_pb2.Behavior,
    'mdx-space-utilization': ext_pb2.SpaceUtilization,
    'mdx-incidents': ext_pb2.Incident,
    'mdx-vlm-incidents': ext_pb2.Incident,
    'vision-llm-events-incidents': ext_pb2.Incident,
    'mdx-vlm': schema_pb2.VisionLLM,
    'mdx-vlm-captions': schema_pb2.VisionLLM,
    'mdx-embed': schema_pb2.VisionLLM,
    'mdx-embed-filtered': schema_pb2.VisionLLM,
    'mdx-structured-events-summary': schema_pb2.VisionLLM,
    'vision-llm-messages': schema_pb2.VisionLLM,
    'vision-embed-messages': schema_pb2.VisionLLM,
}

JSON_SOURCES = frozenset({
    'mdx-amr',
    'mdx-mtmc',
    'mdx-notification',
    'mdx-vlm-errors',
    'mdx-embed-errors',
    'vision-llm-errors',
    'vision-embed-errors',
})
SUPPORTED_SOURCES = tuple(sorted(set(PROTOBUF_SOURCE_TYPES) | JSON_SOURCES))

# Keep this list in lockstep with KAFKA_TOPICS in
# deploy/docker/services/infra/compose.yml. Focused tests compare it directly
# with the Compose source so a newly provisioned topic cannot remain unmapped.
LOCAL_PROVISIONED_SOURCES = frozenset({
    'mdx-alerts',
    'mdx-amr',
    'mdx-behavior',
    'mdx-behavior-plus',
    'mdx-bev',
    'mdx-embed',
    'mdx-embed-filtered',
    'mdx-events',
    'mdx-frames',
    'mdx-incidents',
    'mdx-mtmc',
    'mdx-notification',
    'mdx-raw',
    'mdx-rtls',
    'mdx-rtls-region-1',
    'mdx-space-utilization',
    'mdx-structured-events-summary',
    'mdx-vlm',
    'mdx-vlm-alerts',
    'mdx-vlm-captions',
    'mdx-vlm-incidents',
})

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def non_negative_int_arg(value):
    """Parse a non-negative integer for an argparse ``type`` callback."""
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected a non-negative integer, got {value!r}") from exc
    if parsed < 0:
        raise ValueError(f"expected a non-negative integer, got {value!r}")
    return parsed


def non_negative_float_arg(value):
    """Parse a finite non-negative float for an argparse ``type`` callback."""
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected a non-negative number, got {value!r}") from exc
    if not math.isfinite(parsed) or parsed < 0:
        raise ValueError(f"expected a finite non-negative number, got {value!r}")
    return parsed


def positive_float_arg(value):
    """Parse a finite positive float for an argparse ``type`` callback."""
    parsed = non_negative_float_arg(value)
    if parsed == 0:
        raise ValueError(f"expected a positive number, got {value!r}")
    return parsed


def parse_source_names(value, source_kind):
    """Split a comma-separated source list and reject ambiguous empty names."""
    names = [name.strip() for name in value.split(',')]
    if not names or any(not name for name in names):
        raise ValueError(f"{source_kind} list contains an empty name")
    return names


class BaseMessageConsumer(ABC):
    """Abstract base class for message consumers"""
    
    def __init__(self, args):
        """Initialize base consumer with command line arguments"""
        self.args = args
        self.processes = []
        
    @abstractmethod
    def get_consumer_type(self):
        """Return the type of consumer (e.g., 'Kafka', 'Redis', 'MQTT')"""
        pass
    
    @abstractmethod
    def get_source_names(self):
        """Get list of source names (topics/streams/channels) from args"""
        pass
    
    @abstractmethod
    def create_connection(self, source_name, consumer_group, **kwargs):
        """Create connection to the message broker
        
        Args:
            source_name: The topic/stream/channel name
            consumer_group: Consumer group name
            **kwargs: Additional connection parameters
            
        Returns:
            Connection object specific to the broker type
        """
        pass
    
    @abstractmethod
    def consume_messages(self, connection, source_name, consumer_group, **kwargs):
        """Consume messages from the broker
        
        Args:
            connection: The broker connection object
            source_name: The topic/stream/channel name
            consumer_group: Consumer group name
            **kwargs: Additional parameters specific to the broker
            
        Yields:
            tuple: (message_id, message_data) where message_data is bytes
        """
        pass
    
    @abstractmethod
    def acknowledge_messages(self, connection, source_name, consumer_group, message_ids):
        """Acknowledge processed messages (if applicable for the broker)
        
        Args:
            connection: The broker connection object
            source_name: The topic/stream/channel name
            consumer_group: Consumer group name
            message_ids: List of message IDs to acknowledge
        """
        pass
    
    @abstractmethod
    def close_connection(self, connection):
        """Close the connection to the broker
        
        Args:
            connection: The broker connection object
        """
        pass
    
    @abstractmethod
    def get_connection_info(self):
        """Get connection info string for logging"""
        pass
    
    @staticmethod
    def decode_message(source_name, data):
        """Decode a source-defined protobuf or JSON message to a Python value.
        
        Args:
            source_name: The topic/stream/channel name
            data: Raw protobuf bytes
            
        Returns:
            dict or list: Decoded message, or None if decoding fails
        """
        try:
            message_type = PROTOBUF_SOURCE_TYPES.get(source_name)
            if message_type is not None:
                message = message_type()
                message.ParseFromString(data)
                return MessageToDict(message, preserving_proto_field_name=True)

            if source_name in JSON_SOURCES:
                return json.loads(data.decode('utf-8'))
        except Exception as e:
            # Don't log raw data - it could be huge and/or contain sensitive information
            logger.error(f"Failed to decode message for source {source_name}: {e}")
            return None
        
        logger.error(f"Source {source_name} must be one of the following: {list(SUPPORTED_SOURCES)}")
        return None

    @staticmethod
    def decode_protobuf_message(source_name, data):
        """Backward-compatible alias for callers of the original decoder."""
        return BaseMessageConsumer.decode_message(source_name, data)
    
    def process_source(self, source_name, output_file_path, consumer_group, **connection_params):
        """Process a message source and write to JSON lines file - runs in its own process
        
        Args:
            source_name: The topic/stream/channel name
            output_file_path: Path to the output file
            consumer_group: Consumer group name
            **connection_params: Additional connection parameters
        """
        # Ignore SIGINT in child processes - parent will handle Ctrl+C and send SIGTERM to children
        # This prevents child processes from receiving SIGINT directly when user presses Ctrl+C
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        
        # Set up logging for this process
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logger = logging.getLogger(__name__)
        
        # Create connection for this process
        try:
            connection = self.create_connection(source_name, consumer_group=consumer_group, **connection_params)
        except Exception as e:
            logger.error(f"[{source_name}] Failed to create connection: {e}")
            return {'read': 0, 'written': 0, 'errors': 1}
        
        stats = {'read': 0, 'written': 0, 'errors': 0}
        
        # Flag for clean shutdown
        shutdown_requested = False
        
        def handle_term(signum, frame):
            nonlocal shutdown_requested
            shutdown_requested = True
        
        # Handle SIGTERM for clean shutdown
        signal.signal(signal.SIGTERM, handle_term)
        
        # Open output file for this source
        with open(output_file_path, 'w', encoding='utf-8') as output_file:
            logger.info(f"[{source_name}] Starting processor - output: {output_file_path}")
            logger.info(f"[{source_name}] Connected to {self.get_consumer_type()}: {self.get_connection_info()}")
            first_batch = True
            index = 1
            max_messages = max(0, getattr(self.args, 'max_messages', 0))
            timeout_seconds = max(0.0, getattr(self.args, 'timeout_seconds', 0.0))
            poll_timeout_seconds = max(
                0.001,
                getattr(self.args, 'poll_timeout_seconds', DEFAULT_POLL_TIMEOUT_SECONDS),
            )
            deadline = time.monotonic() + timeout_seconds if timeout_seconds else None
            limit_reached = False
            
            while not shutdown_requested and not limit_reached:
                try:
                    remaining_messages = max_messages - stats['read'] if max_messages else None
                    if remaining_messages is not None and remaining_messages <= 0:
                        logger.info(f"[{source_name}] Reached message limit ({max_messages})")
                        break

                    current_poll_timeout = poll_timeout_seconds
                    if deadline is not None:
                        remaining_seconds = deadline - time.monotonic()
                        if remaining_seconds <= 0:
                            logger.info(f"[{source_name}] Reached timeout ({timeout_seconds:g}s)")
                            break
                        current_poll_timeout = min(current_poll_timeout, remaining_seconds)

                    message_ids = []
                    messages_processed = False
                    consume_params = dict(connection_params)
                    consume_params.update({
                        'max_messages': remaining_messages,
                        'poll_timeout_seconds': current_poll_timeout,
                    })
                    
                    # Consume messages from the broker
                    for msg_id, msg_data in self.consume_messages(
                        connection, source_name, consumer_group, **consume_params
                    ):
                        # Check for special error markers (e.g., Kafka errors)
                        if msg_id == '__kafka_error__':
                            stats['errors'] += 1
                            messages_processed = True
                            if max_messages or timeout_seconds:
                                logger.error(
                                    f"[{source_name}] Stopping bounded capture after Kafka error"
                                )
                                limit_reached = True
                                break
                            continue
                        
                        # Log first batch to confirm processing started
                        if first_batch:
                            logger.info(f"[{source_name}] Started processing messages")
                            first_batch = False
                        
                        stats['read'] += 1
                        messages_processed = True
                        # Decode the protobuf message
                        if msg_data not in (None, b''):
                            output_data = self.decode_message(source_name, msg_data)
                            
                            # Write as JSON line (only the message data, no metadata)
                            if output_data is not None:
                                json.dump(output_data, output_file)
                                output_file.write('\n')
                                output_file.flush()
                                stats['written'] += 1

                                # Acknowledge only after the decoded record has
                                # been written and flushed to the output file.
                                if msg_id is not None and not (
                                    isinstance(msg_id, str) and msg_id.startswith('__')
                                ):
                                    message_ids.append(msg_id)
                            else:
                                stats['errors'] += 1
                                logger.error(
                                    f"[{source_name}] Stopping after message decode failure"
                                )
                                limit_reached = True
                                break
                        else:
                            stats['errors'] += 1
                            logger.error(
                                f"[{source_name}] Stopping after empty or tombstone message payload"
                            )
                            limit_reached = True
                            break
                        
                        if max_messages and stats['read'] >= max_messages:
                            logger.info(f"[{source_name}] Reached message limit ({max_messages})")
                            limit_reached = True
                            break
                    
                    # Acknowledge messages if needed
                    if message_ids:
                        self.acknowledge_messages(connection, source_name, consumer_group, message_ids)
                    
                    # Log stats periodically every 1000 messages
                    if stats['read'] // 1000 == index:
                        logger.info(f"[{source_name}] Read {stats['read']}, Written {stats['written']}, Errors {stats['errors']}")
                        index += 1
                    
                    # If no messages were processed, sleep briefly to avoid busy-waiting
                    if not messages_processed:
                        sleep_seconds = 0.1
                        if deadline is not None:
                            sleep_seconds = min(sleep_seconds, max(0.0, deadline - time.monotonic()))
                        if sleep_seconds:
                            time.sleep(sleep_seconds)
                        
                except (KeyboardInterrupt, SystemExit):
                    # Clean shutdown - no need to log error
                    break
                except Exception as e:
                    if shutdown_requested:
                        # Ignore errors during shutdown
                        break
                    # Only log real errors, not shutdown-related ones
                    logger.error(f"[{source_name}] Error processing: {e}")
                    stats['errors'] += 1
                    # Continuing after a write or explicit-commit failure could
                    # later commit past the failed Kafka record. Stop and let a
                    # restart with the same group replay the uncommitted offset.
                    break
        
        # Clean up
        try:
            self.close_connection(connection)
        except Exception as e:
            logger.error(f"[{source_name}] Error closing connection: {e}")
            stats['errors'] += 1
        
        # Always log final stats when exiting
        logger.info(f"[{source_name}] Final count - Read: {stats['read']}, Written: {stats['written']}, Errors: {stats['errors']}")
        logger.info(f"[{source_name}] Process stopped")
        return stats

    def process_source_entrypoint(
        self,
        source_name,
        output_file_path,
        consumer_group,
        **connection_params,
    ):
        """Run one source and expose processing errors as a child exit code."""
        stats = self.process_source(
            source_name,
            output_file_path,
            consumer_group,
            **connection_params,
        )
        if stats['errors']:
            raise SystemExit(1)
    
    def run(self):
        """Main method to run the consumer"""
        # Parse source names
        try:
            source_names = self.get_source_names()
        except ValueError as exc:
            logger.error(f"Invalid source list: {exc}")
            return False
        
        # Create output directory if it doesn't exist
        os.makedirs(self.args.output_dir, exist_ok=True)
        
        # Startup logging
        consumer_type = self.get_consumer_type()
        logger.info(f"\n{'='*60}")
        logger.info(f"{consumer_type} to JSON Lines Dumper - Starting up")
        logger.info(f"{'='*60}")
        logger.info(f"Output directory: {self.args.output_dir}")
        logger.info(f"{consumer_type} connection: {self.get_connection_info()}")
        logger.info(f"Consumer group: {self.args.consumer_group}")
        logger.info(f"Sources to process: {', '.join(source_names)}")
        max_messages = max(0, getattr(self.args, 'max_messages', 0))
        timeout_seconds = max(0.0, getattr(self.args, 'timeout_seconds', 0.0))
        if max_messages:
            logger.info(f"Per-source message limit: {max_messages}")
        if timeout_seconds:
            logger.info(f"Per-source timeout: {timeout_seconds:g}s")
        logger.info(f"{'='*60}\n")
        
        def signal_handler(signum, frame):
            signal_name = 'SIGINT (Ctrl+C)' if signum == signal.SIGINT else 'SIGTERM'
            logger.info(f"\n{'='*60}")
            logger.info(f"Received {signal_name} - shutting down...")
            
            # Send termination signal to all processes
            for p in self.processes:
                if p.is_alive():
                    with suppress(Exception):
                        p.terminate()
            
            # Wait briefly for processes to terminate
            for p in self.processes:
                with suppress(Exception):
                    p.join(timeout=2)
            
            logger.info("Shutdown complete")
            logger.info(f"{'='*60}\n")
            sys.exit(0)
        
        # Set up signal handlers for the main process
        # Child processes will ignore SIGINT (set in process_source)
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        run_succeeded = False
        try:

            # Start a process for each source
            for source_name in source_names:
                process_args = self.get_process_args(source_name)
                
                logger.info(f"Starting process for source: {source_name} -> {process_args['output_file_path']}")
                
                process = Process(
                    target=self.process_source_entrypoint,
                    args=(source_name, process_args['output_file_path'], 
                          self.args.consumer_group),
                    kwargs=process_args.get('connection_params', {}),
                    name=f"process-{source_name}"
                )
                process.start()
                self.processes.append(process)
            
            logger.info(f"Started {len(self.processes)} process(es) for sources: {', '.join(source_names)}")
            logger.info("Press Ctrl+C to stop all processes gracefully")
            logger.info(f"{'='*60}\n")
            
            # Monitor processes
            monitor_interval_seconds = 0.2 if max_messages or timeout_seconds else 5.0
            last_status_at = time.monotonic()
            reported_dead_processes = set()
            while True:
                alive_count = 0
                dead_processes = []
                
                for p in self.processes:
                    if p.is_alive():
                        alive_count += 1
                    else:
                        dead_processes.append(p)
                
                # Report dead processes
                for p in dead_processes:
                    if p.name not in reported_dead_processes:
                        logger.warning(
                            f"Process {p.name} is no longer running (exit code: {p.exitcode})"
                        )
                        reported_dead_processes.add(p.name)
                
                # Periodic status update every 30 seconds
                now = time.monotonic()
                if now - last_status_at >= 30:
                    logger.info(f"Status: {alive_count}/{len(self.processes)} processes running")
                    last_status_at = now
                
                if alive_count == 0:
                    failed_processes = [p for p in self.processes if p.exitcode != 0]
                    if failed_processes:
                        failed_names = ', '.join(p.name for p in failed_processes)
                        logger.error(f"Consumer process failures: {failed_names}")
                    elif max_messages or timeout_seconds:
                        logger.info("All bounded consumer processes have completed")
                        run_succeeded = True
                    else:
                        logger.error("All processes have died - exiting")
                    break
                
                time.sleep(monitor_interval_seconds)
                
        except KeyboardInterrupt:
            run_succeeded = True
        except Exception as e:
            logger.error(f"Unexpected error in main loop: {e}")
        finally:
            # Ensure all processes are terminated
            for p in self.processes:
                if p.is_alive():
                    try:
                        p.terminate()
                        p.join(timeout=2)
                        if p.is_alive():
                            p.kill()
                            p.join()
                    except Exception as e:
                        logger.error(f"[{p.name}] Error terminating process: {e}")
            logger.info(f"{consumer_type} to JSON Lines Dumper shutdown complete")
            logger.info(f"{'='*60}\n")

        return run_succeeded
    
    @abstractmethod
    def get_process_args(self, source_name):
        """Get process arguments for a specific source
        
        Args:
            source_name: The topic/stream/channel name
            
        Returns:
            dict: Contains 'output_file_path' and 'connection_params'
        """
        pass
