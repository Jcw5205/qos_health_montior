#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.qos import ReliabilityPolicy
import tkinter as tk
from tkinter import ttk
import threading

class TopicMonitor(Node):
    def __init__(self):
        super().__init__('qos_health_node')
        self.topics_info = {}
        self.update_interval = 1000  # ms
        self.setup_topics()
        self.create_gui()

    def setup_topics(self):
        topic_list = self.get_topic_names_and_types()
        for topic, types in topic_list:
            publishers_info = self.get_publishers_info_by_topic(topic)
            subscribers_info = self.get_subscriptions_info_by_topic(topic)

            # Format reliability per publisher
            pub_list = []
            for pub in publishers_info:
                rel = "RELIABLE" if pub.qos_profile.reliability == ReliabilityPolicy.RELIABLE else "BEST_EFFORT"
                pub_list.append(f"{pub.node_name} ({rel})")

            pub_count = len(publishers_info)  # actual number of publisher handles
            pub_display = f"{pub_count}: " + ', '.join(pub_list)


            self.topics_info[topic] = {
                'msg_type': ', '.join(types),
                'publishers': pub_list,
                'subscribers': [sub.node_name for sub in subscribers_info],
            }

    def create_gui(self):
        self.root = tk.Tk()
        self.root.title("ROS 2 Active Topics")

        # Only one tab: Nodes per Topic
        self.tab_nodes = ttk.Frame(self.root)
        self.tab_nodes.pack(fill=tk.BOTH, expand=True)

        columns_nodes = ("Topic", "Publishers", "Subscribers")
        self.tree_nodes = ttk.Treeview(self.tab_nodes, columns=columns_nodes, show='headings')
        for col in columns_nodes:
            self.tree_nodes.heading(col, text=col)
        self.tree_nodes.pack(fill=tk.BOTH, expand=True)

        self.update_tree()

    def update_tree(self):
        # Clear and repopulate nodes per topic
        for item in self.tree_nodes.get_children():
            self.tree_nodes.delete(item)
        for topic, info in self.topics_info.items():
            pubs = f"{len(info['publishers'])}: " + ', '.join(info['publishers']) if info['publishers'] else "0"
            subs = ', '.join(info['subscribers']) if info['subscribers'] else "None"
            self.tree_nodes.insert("", tk.END, values=(topic, pubs, subs))

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
