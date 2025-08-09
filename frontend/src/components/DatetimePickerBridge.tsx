import React, { useState } from 'react';
import { DatetimePicker } from './ui/datetime-picker';

interface DatetimePickerBridgeProps {
  onDateChange?: (date: Date | undefined) => void;
  initialValue?: Date;
  className?: string;
}

export const DatetimePickerBridge: React.FC<DatetimePickerBridgeProps> = ({
  onDateChange,
  initialValue,
  className
}) => {
  const [selectedDate, setSelectedDate] = useState<Date | undefined>(initialValue);

  const handleDateChange = (date: Date | undefined) => {
    setSelectedDate(date);
    if (onDateChange) {
      onDateChange(date);
    }
  };

  return (
    <div className={className}>
      <DatetimePicker
        value={selectedDate}
        onChange={handleDateChange}
        format={[
          ["months", "days", "years"],
          ["hours", "minutes", "am/pm"],
        ]}
      />
    </div>
  );
};

export default DatetimePickerBridge;
