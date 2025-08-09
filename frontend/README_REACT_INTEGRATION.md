# React Component Integration for Zavion Frontend

This document provides a complete guide for integrating React components into the existing Zavion frontend application.

## 🎯 Overview

The integration adds React/TypeScript support to the existing vanilla JavaScript application, specifically for the `datetime-picker.tsx` component and its dependencies.

## 📁 Project Structure

```
frontend/
├── src/                          # React source code
│   ├── components/
│   │   ├── ui/
│   │   │   ├── datetime-picker.tsx      # Main datetime picker component
│   │   │   ├── datetime-picker-demo.tsx # Demo component
│   │   │   ├── input.tsx                # shadcn input component
│   │   │   └── index.ts                 # Component exports
│   │   └── DatetimePickerBridge.tsx     # Bridge component for integration
│   ├── lib/
│   │   └── utils.ts                     # Utility functions (cn, etc.)
│   ├── utils/
│   │   └── react-bridge.ts              # Bridge utilities for vanilla JS
│   ├── App.tsx                          # Main React app
│   ├── main.tsx                         # React entry point
│   └── index.css                        # Tailwind CSS styles
├── package.json                         # Dependencies and scripts
├── tsconfig.json                        # TypeScript configuration
├── tsconfig.node.json                   # Node.js TypeScript config
├── vite.config.ts                       # Vite configuration
├── tailwind.config.js                   # Tailwind CSS configuration
├── postcss.config.js                    # PostCSS configuration
├── REACT_SETUP.md                       # Detailed setup guide
└── integration-example.html             # Integration example
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
cd frontend
npm install
```

### 2. Development Mode

```bash
# Start React development server
npm run dev

# This will start the server at http://localhost:3000
```

### 3. Build for Production

```bash
npm run build
```

## 🎨 Components

### DatetimePicker Component

The main `datetime-picker.tsx` component provides:

- **Modern UI**: Clean, accessible datetime picker interface
- **TypeScript Support**: Fully typed with TypeScript
- **Customizable**: Configurable format and styling
- **Accessible**: ARIA-compliant and keyboard navigable

#### Usage Example

```tsx
import { DatetimePicker } from '@/components/ui/datetime-picker';

function MyComponent() {
  return (
    <DatetimePicker
      format={[
        ["months", "days", "years"],
        ["hours", "minutes", "am/pm"],
      ]}
      onChange={(date) => console.log('Date selected:', date)}
    />
  );
}
```

### Integration Bridge

The `react-bridge.ts` utility allows seamless integration with the existing vanilla JavaScript application:

```javascript
import { mountDatetimePicker } from './src/utils/react-bridge';

// Mount the datetime picker in an existing DOM element
const datetimePicker = mountDatetimePicker('datetime-picker-container', {
  onDateChange: (date) => {
    console.log('Date selected:', date);
    // Handle date change in existing app
  },
  initialValue: new Date(),
  className: 'datetime-picker-wrapper'
});
```

## 🔧 Configuration

### TypeScript Configuration

The project uses TypeScript with strict mode enabled. Key configurations:

- **Path Aliases**: `@/` points to `src/`
- **JSX**: React JSX mode enabled
- **Strict Mode**: Full type checking enabled

### Tailwind CSS

Tailwind CSS is configured with:

- **Custom Colors**: shadcn/ui color palette
- **Dark Mode**: Class-based dark mode support
- **Animations**: Built-in animation utilities

### Vite Configuration

Vite is configured for:

- **React Support**: JSX and TypeScript support
- **Path Resolution**: Custom path aliases
- **Development Server**: Hot reload and proxy configuration

## 📚 API Reference

### DatetimePicker Props

```typescript
interface DateTimeInput {
  value?: Date;                           // Current date value
  format?: DateTimeFormatDefaults;        // Date/time format
  placeholders?: InputPlaceholders;       // Custom placeholders
  onChange?: (date: Date | undefined) => void; // Change handler
  dtOptions?: Options;                    // Timescape options
  className?: string;                     // Additional CSS classes
}
```

### Bridge Utilities

```typescript
// Mount a React component
function mountReactComponent(
  elementId: string,
  Component: React.ComponentType<any>,
  props?: any
): ReactDOM.Root | null;

// Mount the datetime picker specifically
function mountDatetimePicker(
  elementId: string,
  props?: DatetimePickerBridgeProps
): ReactDOM.Root | null;

// Unmount a component
function unmountReactComponent(elementId: string): void;

// Cleanup all components
function cleanupReactComponents(): void;
```

## 🎯 Integration Examples

### Example 1: Basic Integration

```html
<!-- Add this to your existing HTML -->
<div id="datetime-picker-container"></div>

<script type="module">
  import { mountDatetimePicker } from './src/utils/react-bridge';
  
  mountDatetimePicker('datetime-picker-container', {
    onDateChange: (date) => {
      console.log('Date selected:', date);
    }
  });
</script>
```

### Example 2: With Styling

```html
<div id="datetime-picker-container" class="my-custom-wrapper"></div>

<script type="module">
  import { mountDatetimePicker } from './src/utils/react-bridge';
  
  mountDatetimePicker('datetime-picker-container', {
    onDateChange: (date) => {
      // Handle date change
    },
    className: 'datetime-picker-custom',
    initialValue: new Date()
  });
</script>
```

## 🐛 Troubleshooting

### Common Issues

1. **Module not found errors**
   ```bash
   # Clear and reinstall dependencies
   rm -rf node_modules package-lock.json
   npm install
   ```

2. **TypeScript errors**
   ```bash
   # Check for type issues
   npm run type-check
   ```

3. **Styling issues**
   - Ensure Tailwind CSS is properly configured
   - Check that CSS variables are defined in `src/index.css`

4. **React component not rendering**
   - Verify the container element exists with the correct ID
   - Check browser console for errors
   - Ensure React and ReactDOM are properly loaded

### Build Issues

```bash
# Clear build cache
rm -rf dist

# Rebuild
npm run build

# Check for issues
npm run type-check
```

## 🔄 Migration Strategy

This integration is designed for gradual migration:

1. **Phase 1**: Add React components alongside existing code
2. **Phase 2**: Gradually replace vanilla JS components with React
3. **Phase 3**: Full React migration (optional)

The bridge utilities ensure smooth coexistence during the transition.

## 📄 License

This integration follows the same license as the main Zavion project.

## 🤝 Contributing

When adding new React components:

1. Follow the existing structure in `src/components/ui/`
2. Add proper TypeScript types
3. Include documentation and examples
4. Update the bridge utilities if needed
5. Test integration with existing code

## 📞 Support

For issues related to:

- **React/TypeScript**: Check the `REACT_SETUP.md` file
- **Integration**: Review the bridge utilities and examples
- **Styling**: Consult Tailwind CSS documentation
- **Build**: Check Vite and TypeScript configurations
