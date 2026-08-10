/**
 * Minimal read-only rosbridge client.
 *
 * The browser connects only to the authenticated `/ws/ros` proxy. This class
 * intentionally exposes no advertise, publish, service, parameter or action
 * methods.
 */

import * as ROSLIB from 'roslib';


export class RosbridgeConnection {
  private ros: ROSLIB.Ros | null = null;
  private subscribers = new Map<string, {
    topic: ROSLIB.Topic;
    messageType: string;
    callbacks: Set<(message: unknown) => void>;
  }>();

  async connect(url: string): Promise<boolean> {
    return new Promise((resolve) => {
      let settled = false;
      const finish = (result: boolean) => {
        if (!settled) {
          settled = true;
          resolve(result);
        }
      };
      try {
        this.ros = new ROSLIB.Ros({ url });
        this.ros.on('connection', () => finish(true));
        this.ros.on('error', (error) => {
          console.error('Read-only rosbridge error:', error);
          finish(false);
        });
        this.ros.on('close', () => {
          if (!settled) finish(false);
        });
      } catch (error) {
        console.error('Failed to create read-only rosbridge connection:', error);
        finish(false);
      }
    });
  }

  disconnect(): void {
    for (const subscription of this.subscribers.values()) {
      subscription.topic.unsubscribe();
    }
    this.subscribers.clear();
    this.ros?.close();
    this.ros = null;
  }

  isConnected(): boolean {
    return this.ros?.isConnected ?? false;
  }

  async initializeMessageReaders(): Promise<void> {
    // Fixed layer types use ordinary rosbridge JSON; rosapi is deliberately
    // unavailable through the read-only proxy.
  }

  getTopicType(_topicName: string): string | undefined {
    return undefined;
  }

  subscribe(
    topicName: string,
    messageType: string,
    callback: (message: unknown) => void,
  ): () => void {
    if (!this.ros?.isConnected) {
      throw new Error('ROS visualization is not connected');
    }

    const existing = this.subscribers.get(topicName);
    if (existing) {
      if (existing.messageType !== messageType) {
        throw new Error(`Topic ${topicName} is already subscribed with a different message type`);
      }
      existing.callbacks.add(callback);
      return () => this.unsubscribeCallback(topicName, callback);
    }

    const topic = new ROSLIB.Topic({
      ros: this.ros,
      name: topicName,
      messageType,
      compression: 'none',
      throttle_rate: 0,
      queue_length: 1,
    });
    const callbacks = new Set<(message: unknown) => void>([callback]);
    topic.subscribe((message) => {
      for (const subscriber of callbacks) subscriber(message);
    });
    this.subscribers.set(topicName, { topic, messageType, callbacks });
    return () => this.unsubscribeCallback(topicName, callback);
  }

  unsubscribe(topicName: string): void {
    const subscription = this.subscribers.get(topicName);
    if (subscription) {
      subscription.topic.unsubscribe();
      this.subscribers.delete(topicName);
    }
  }

  private unsubscribeCallback(
    topicName: string,
    callback: (message: unknown) => void,
  ): void {
    const subscription = this.subscribers.get(topicName);
    if (!subscription) return;
    subscription.callbacks.delete(callback);
    if (subscription.callbacks.size === 0) {
      subscription.topic.unsubscribe();
      this.subscribers.delete(topicName);
    }
  }
}
