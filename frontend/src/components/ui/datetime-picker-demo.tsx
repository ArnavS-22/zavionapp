import React from "react";
import { DatetimePicker } from "@/components/ui/datetime-picker";

const DatetimePickerDemo = () => {
  return (
    <DatetimePicker
      format={[
        ["months", "days", "years"],
        ["hours", "minutes", "am/pm"],
      ]}
    />
  );
};

export { DatetimePickerDemo };
