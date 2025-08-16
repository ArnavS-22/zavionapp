import React from 'react';
import ReactDOM from 'react-dom/client';
import { DatetimePickerBridge } from '../components/DatetimePickerBridge';

// Global registry for React component instances
const reactInstances = new Map<string, ReactDOM.Root>();

/**
 * Mounts a React component into a DOM element
 * @param elementId - The ID of the DOM element to mount the component into
 * @param Component - The React component to mount
 * @param props - Props to pass to the component
 * @returns The React root instance
 */
export function mountReactComponent(
  elementId: string,
  Component: React.ComponentType<any>,
  props: any = {}
): ReactDOM.Root | null {
  const element = document.getElementById(elementId);
  if (!element) {
    console.error(`Element with ID "${elementId}" not found`);
    return null;
  }

  // Clean up existing instance if it exists
  if (reactInstances.has(elementId)) {
    const existingRoot = reactInstances.get(elementId);
    if (existingRoot) {
      existingRoot.unmount();
    }
  }

  // Create new React root
  const root = ReactDOM.createRoot(element);
  root.render(React.createElement(Component, props));
  
  // Store the instance
  reactInstances.set(elementId, root);
  
  return root;
}

/**
 * Unmounts a React component from a DOM element
 * @param elementId - The ID of the DOM element
 */
export function unmountReactComponent(elementId: string): void {
  const root = reactInstances.get(elementId);
  if (root) {
    root.unmount();
    reactInstances.delete(elementId);
  }
}

/**
 * Mounts the DatetimePicker component into a DOM element
 * @param elementId - The ID of the DOM element to mount into
 * @param props - Props to pass to the DatetimePickerBridge
 * @returns The React root instance
 */
export function mountDatetimePicker(
  elementId: string,
  props: {
    onDateChange?: (date: Date | undefined) => void;
    initialValue?: Date;
    className?: string;
  } = {}
): ReactDOM.Root | null {
  return mountReactComponent(elementId, DatetimePickerBridge, props);
}

/**
 * Cleanup function to unmount all React components
 */
export function cleanupReactComponents(): void {
  reactInstances.forEach((root, elementId) => {
    root.unmount();
  });
  reactInstances.clear();
}
