#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.time import Time
from rclpy.serialization import serialize_message, deserialize_message
from rosidl_runtime_py.utilities import get_message
from std_msgs.msg import String
import rosbag2_py 
from rosbag2_py import SequentialReader, SequentialWriter, StorageOptions, ConverterOptions, TopicMetadata
from rclpy.qos import ReliabilityPolicy, QoSProfile, QoSHistoryPolicy, QoSPresetProfiles
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import pandas as pd
import time
import csv
import shutil
from pathlib import Path
from collections import defaultdict


class TopicMonitor(Node):
    def __init__(self):
        super().__init__('qos_health_node')
        self.topics_info = {}
        self.update_interval = 1000
        self.setup_topics()

        self.sub_dict = {}
        self.message_counts = {}
        self.is_recording = False
        self.db_lock = threading.Lock()

        self.qos_metrics = defaultdict(lambda: {
            'message_rate': 0.0,
            'latency_ms': 0.0,
            'jitter_ms': 0.0,
            'message_size': 0,
            'last_receive_time': None,
            'inter_arrival_times': [],
            'msg_timestamps': []
        })

        self.bag_writer = None
        self.bag_path = None
        self.discovery_timer = None

        self.create_gui()
        self.refresh_timer = self.create_timer(2.0, self.setup_topics)


    def setup_topics(self):
        topic_list = self.get_topic_names_and_types()
        for topic, types in topic_list:
            publishers_info = self.get_publishers_info_by_topic(topic)
            subscribers_info = self.get_subscriptions_info_by_topic(topic)

            pub_list = []
            for pub in publishers_info:
                rel = "RELIABLE" if pub.qos_profile.reliability == ReliabilityPolicy.RELIABLE else "BEST_EFFORT"
                pub_list.append(f"{pub.node_name} ({rel})")

            self.topics_info[topic] = {
                'msg_type': ', '.join(types),
                'publishers': pub_list,
                'subscribers': [sub.node_name for sub in subscribers_info],
            }

    def discover_and_subscribe(self):
        topic_list = self.get_topic_names_and_types()

        for topic_name, types in topic_list:
            if topic_name in self.sub_dict or topic_name.startswith('/parameter_events') or topic_name.startswith('/rosout'):
                continue
            
            msg_type_str = types[0]

            try:
                msg_type = self.get_msg_type(msg_type_str)

                if msg_type:
                    try:
                        topic_metadata = TopicMetadata(
                            name=topic_name,
                            type=msg_type_str,
                            serialization_format='cdr'
                        )
                        self.bag_writer.create_topic(topic_metadata)
                    except Exception as e:
                        self.get_logger().warn(f'Topic already exists in bag: {topic_name}')
                        
                    qos_profile = QoSProfile(
                        reliability=ReliabilityPolicy.RELIABLE,
                        history=QoSHistoryPolicy.KEEP_LAST,  
                        depth=10
                    )
                    
                    try:
                        subscription = self.create_subscription(  
                            msg_type,
                            topic_name,
                            lambda msg, topic=topic_name, msg_type_str=msg_type_str: self.message_callback(msg, topic, msg_type_str), 
                            qos_profile
                        )
                    except Exception:
                        qos_profile = QoSProfile(
                            reliability=ReliabilityPolicy.BEST_EFFORT,
                            history=QoSHistoryPolicy.KEEP_LAST,  
                            depth=10
                        )
                        subscription = self.create_subscription(  
                            msg_type,
                            topic_name,
                            lambda msg, topic=topic_name, msg_type_str=msg_type_str: self.message_callback(msg, topic, msg_type_str), 
                            qos_profile
                        )
                    
                    self.sub_dict[topic_name] = subscription  
                    self.message_counts[topic_name] = 0
                    
                    self.get_logger().info(f'Subscribed to: {topic_name}')
                    
            except Exception as e:
                self.get_logger().warn(f'Failed to subscribe to {topic_name}: {str(e)}')
    

    def get_msg_type(self, msg_type_str):
        try:
            parts = msg_type_str.split('/')
            if len(parts) == 3:
                package, msg_folder, msg_name = parts
                module_name = f'{package}.{msg_folder}'
                module = __import__(module_name, fromlist=[msg_name])
                return getattr(module, msg_name)
        except Exception as e:
            self.get_logger().warn(f'Could not import {msg_type_str}: {str(e)}')

        return None

    def auto_start_recording(self):
        try:
            self.get_logger().info('Auto-start recording initiated...')
            
            script_dir = Path(__file__).parent
            default_bag_dir = script_dir / "ros2_bags"
            
            self.get_logger().info(f'Creating bag in: {default_bag_dir}')
            
            self.init_rosbag(str(default_bag_dir))
            self.is_recording = True
            self.btn_stop.config(state=tk.NORMAL)
            self.status_label.config(text=f"Recording to: {self.bag_path.name}", foreground="red")
            
            self.discovery_timer = self.create_timer(1.0, self.discover_and_subscribe)
            
            self.get_logger().info(f'✓ Auto-started recording to: {self.bag_path}')
            
        except Exception as e:
            self.get_logger().error(f'Failed to auto-start recording: {str(e)}')
            self.status_label.config(text=f"Error: {str(e)}", foreground="red")

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False

        for topic_name, subscription in self.sub_dict.items():
            self.destroy_subscription(subscription)
            
        self.sub_dict.clear()
        
        if self.bag_writer:
            try:
                del self.bag_writer
            except Exception as e:
                self.get_logger().warn(f'Error closing bag writer: {str(e)}')
            self.bag_writer = None
        
        if self.discovery_timer is not None:
            self.discovery_timer.cancel()
            self.discovery_timer = None
        
        self.btn_stop.config(state=tk.DISABLED)
        
        total_messages = sum(self.message_counts.values())
        self.status_label.config(text=f"Converting to CSV...", foreground="orange")
        
        csv_file = self.convert_bag_to_csv()
        
        self.status_label.config(text=f"Recording stopped. Total messages: {total_messages}", foreground="green")
        
        if csv_file:
            messagebox.showinfo(
                "Recording Complete",
                f"Saved {total_messages} messages to:\n{self.bag_path}\n\n"
                f"CSV file created:\n{csv_file}\n\n"
                f"Play with: ros2 bag play {self.bag_path}\n"
                f"Analyze with: ros2 bag info {self.bag_path}"
            )
        else:
            messagebox.showinfo(
                "Recording Complete",
                f"Saved {total_messages} messages to:\n{self.bag_path}\n\n"
                f"Play with: ros2 bag play {self.bag_path}\n"
                f"Analyze with: ros2 bag info {self.bag_path}"
            )
        
        self.get_logger().info(f'Recording stopped. Total messages: {total_messages}')

    def message_callback(self, msg, topic_name, msg_type_str):
        if not self.is_recording or self.bag_writer is None:
            return

        receive_time = time.time()
        timestamp_nanosec = self.get_clock().now().nanoseconds 

        msg_timestamp_sec = 0
        msg_timestamp_nanosec = 0
        
        if hasattr(msg, 'header') and hasattr(msg.header, 'stamp'):
            msg_timestamp_sec = msg.header.stamp.sec
            msg_timestamp_nanosec = msg.header.stamp.nanosec

        try:
            serialized = serialize_message(msg)
            data_size = len(serialized)
        except Exception as e:
            self.get_logger().error(f'Error serializing message: {str(e)}')
            return

        try:
            self.bag_writer.write(topic_name, serialized, timestamp_nanosec)
        except Exception as e:
            self.get_logger().error(f'Error writing to bag: {str(e)}')
            return
    
        self.message_counts[topic_name] += 1
        
        metrics = self.qos_metrics[topic_name]
  
        if topic_name in self.sub_dict:
            try:
          
                pub_stats = self.sub_dict[topic_name].get_publisher_matched_status()

                
            except Exception as e:
                pass 
        
  
        msg_timestamp = msg_timestamp_sec + msg_timestamp_nanosec * 1e-9

        if msg_timestamp > 0:
            latency = receive_time - msg_timestamp
            metrics['latency_ms'] = latency * 1000
            metrics['msg_timestamps'].append(msg_timestamp)  
            
            if len(metrics['msg_timestamps']) > 100:
                metrics['msg_timestamps'].pop(0)
        else:
   
            if metrics['last_receive_time'] is not None:
                inter_arrival = receive_time - metrics['last_receive_time']
  
                metrics['latency_ms'] = inter_arrival * 1000
    
        if metrics['last_receive_time'] is not None:
            inter_arrival = receive_time - metrics['last_receive_time']
            metrics['inter_arrival_times'].append(inter_arrival)
            
            if len(metrics['inter_arrival_times']) > 100:
                metrics['inter_arrival_times'].pop(0)
            
            if len(metrics['inter_arrival_times']) > 1:
                mean_inter_arrival = sum(metrics['inter_arrival_times']) / len(metrics['inter_arrival_times'])
                variance = sum((x - mean_inter_arrival) ** 2 for x in metrics['inter_arrival_times']) / len(metrics['inter_arrival_times'])
                metrics['jitter_ms'] = (variance ** 0.5) * 1000
                
                if mean_inter_arrival > 0:
                    metrics['message_rate'] = 1.0 / mean_inter_arrival
        
        metrics['last_receive_time'] = receive_time
        metrics['message_size'] = data_size

    def init_rosbag(self, bag_path):
        base_path = Path(bag_path)
        base_path.mkdir(parents=True, exist_ok=True)
        
        self.bag_path = base_path / "rosbag2_recording"
        
        if self.bag_path.exists():
            self.get_logger().info(f'Removing existing bag: {self.bag_path}')
            try:
                shutil.rmtree(self.bag_path)
                time.sleep(0.2)
                self.get_logger().info('Old bag removed successfully')
            except Exception as e:
                self.get_logger().error(f'Error removing old bag: {e}')
                raise

        storage_options = StorageOptions(uri=str(self.bag_path), storage_id='sqlite3')
        converter_options = ConverterOptions(input_serialization_format='cdr', output_serialization_format='cdr')
        
        self.bag_writer = SequentialWriter()
        self.bag_writer.open(storage_options, converter_options)
        
        self.get_logger().info(f'ROS bag initialized: {self.bag_path}')

    def convert_bag_to_csv(self):
        try:
            self.get_logger().info('Starting bag to CSV conversion...')
            
            csv_path = self.bag_path.parent / f"{self.bag_path.name}.csv"
            
            storage_options = StorageOptions(uri=str(self.bag_path), storage_id='sqlite3')
            converter_options = ConverterOptions(input_serialization_format='cdr', output_serialization_format='cdr')
            
            reader = SequentialReader()
            reader.open(storage_options, converter_options)
            
            topic_types = reader.get_all_topics_and_types()
            type_map = {topic.name: topic.type for topic in topic_types}
            
            rows = []
            
            while reader.has_next():
                (topic, data, timestamp) = reader.read_next()
                
                try:
                    msg_type = get_message(type_map[topic])
                    msg = deserialize_message(data, msg_type)
                except Exception as e:
                    self.get_logger().warn(f'Could not deserialize message on {topic}: {e}')
                    continue
                
                time_sec = timestamp / 1e9
                
                row = {'timestamp': time_sec, 'topic': topic, 'msg_type': type_map[topic]}
                
                def extract_fields(obj, prefix=''):
                    if hasattr(obj, '__slots__'):
                        for slot in obj.__slots__:
                            attr = getattr(obj, slot, None)
                            if attr is not None:
                                key = f"{prefix}{slot}" if prefix else slot
                                if hasattr(attr, '__slots__'):
                                    extract_fields(attr, f"{key}_")
                                elif isinstance(attr, (int, float, str, bool)):
                                    row[key] = attr
                                else:
                                    row[key] = str(attr)
                
                extract_fields(msg)
                rows.append(row)
            
            if rows:
                all_keys = set()
                for row in rows:
                    all_keys.update(row.keys())
                
                fieldnames = ['timestamp', 'topic', 'msg_type'] + sorted(list(all_keys - {'timestamp', 'topic', 'msg_type'}))
                
                with open(csv_path, 'w', newline='') as csvfile:
                    writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                    writer.writeheader()
                    writer.writerows(rows)
                
                self.get_logger().info(f'✓ CSV file created: {csv_path}')
                self.get_logger().info(f'  Total rows: {len(rows)}')
                return csv_path
            else:
                self.get_logger().warn('No messages to convert to CSV')
                return None
                
        except Exception as e:
            self.get_logger().error(f'Error converting bag to CSV: {str(e)}')
            import traceback
            self.get_logger().error(traceback.format_exc())
            return None

    def create_gui(self):
        self.root = tk.Tk()
        self.root.title("ROS 2 QoS Monitor with Recording")
        self.root.geometry("1200x700")  
        
        control_frame = ttk.Frame(self.root, padding="5")
        control_frame.pack(fill=tk.X)
        
        self.btn_stop = ttk.Button(control_frame, text="Stop Recording", command=self.stop_recording, state=tk.DISABLED)
        self.btn_stop.pack(side=tk.LEFT, padx=5)
        
        self.status_label = ttk.Label(control_frame, text="Initializing...", foreground="blue")
        self.status_label.pack(side=tk.LEFT, padx=20)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        
        self.tab_topics = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_topics, text="Topics")
        
        columns_nodes = ("Topic", "Publishers", "Subscribers")
        self.tree_nodes = ttk.Treeview(self.tab_topics, columns=columns_nodes, show='headings')
        for col in columns_nodes:
            self.tree_nodes.heading(col, text=col)
            self.tree_nodes.column(col, width=200)
        self.tree_nodes.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_metrics = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_metrics, text="QoS Metrics")
        
        columns_metrics = ("Topic", "Messages", "Rate (Hz)", "Latency (ms)", "Jitter (ms)", "Size (bytes)")
        self.tree_metrics = ttk.Treeview(self.tab_metrics, columns=columns_metrics, show='headings', height=20)
        for col in columns_metrics:
            self.tree_metrics.heading(col, text=col)
            self.tree_metrics.column(col, width=150)
        self.tree_metrics.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        self.tab_info = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_info, text="Recording Info")
        
        info_frame = ttk.Frame(self.tab_info, padding="10")
        info_frame.pack(fill=tk.BOTH, expand=True)
        
        ttk.Label(info_frame, text="Recording Status:", font=("Arial", 12, "bold")).pack(anchor=tk.W)
        self.info_recording = ttk.Label(info_frame, text="Not recording", font=("Arial", 11))
        self.info_recording.pack(anchor=tk.W, padx=20)
        
        ttk.Label(info_frame, text="ROS Bag Location:", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(20, 0))
        self.info_location = ttk.Label(info_frame, text="None", font=("Arial", 11), foreground="blue")
        self.info_location.pack(anchor=tk.W, padx=20)
        
        ttk.Label(info_frame, text="Total Messages by Topic:", font=("Arial", 12, "bold")).pack(anchor=tk.W, pady=(20, 0))
        self.info_text = tk.Text(info_frame, height=15, width=80)
        self.info_text.pack(fill=tk.BOTH, expand=True, padx=20)

        self.update_tree()
        self.root.after(1000, self.auto_start_recording)

    def update_tree(self):
        for item in self.tree_nodes.get_children():
            self.tree_nodes.delete(item)
        
        for topic, info in self.topics_info.items():
            pubs = f"{len(info['publishers'])}: " + ', '.join(info['publishers'])
            subs = ', '.join(info['subscribers']) if info['subscribers'] else "None"
            self.tree_nodes.insert("", tk.END, values=(topic, pubs, subs))

        for item in self.tree_metrics.get_children():
            self.tree_metrics.delete(item)
        
        if self.is_recording:
            for topic_name, metrics in self.qos_metrics.items():
                msg_count = self.message_counts.get(topic_name, 0)
                self.tree_metrics.insert("", tk.END, values=(
                    topic_name,
                    msg_count,
                    f"{metrics['message_rate']:.2f}",
                    f"{metrics['latency_ms']:.3f}",
                    f"{metrics['jitter_ms']:.3f}",
                    metrics['message_size']
                ))

        if self.is_recording:
            self.info_recording.config(text="Currently Recording ●", foreground="red")
            self.info_location.config(text=str(self.bag_path))
        else:
            self.info_recording.config(text="Not Recording", foreground="gray")
            self.info_location.config(text="None")
        
        self.info_text.config(state=tk.NORMAL)
        self.info_text.delete(1.0, tk.END)
        
        if self.message_counts:
            info_str = ""
            total = 0
            for topic, count in sorted(self.message_counts.items()):
                info_str += f"{topic}: {count} messages\n"
                total += count
            info_str += f"\n{'='*50}\nTotal: {total} messages"
            self.info_text.insert(tk.END, info_str)
        
        self.info_text.config(state=tk.DISABLED)
        self.root.after(self.update_interval, self.update_tree)

def spin_ros(node):
    rclpy.spin(node)

def main(args=None):
    rclpy.init(args=args)
    node = TopicMonitor()

    ros_thread = threading.Thread(target=spin_ros, args=(node,), daemon=True)
    ros_thread.start()

    node.root.mainloop()

    node.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()