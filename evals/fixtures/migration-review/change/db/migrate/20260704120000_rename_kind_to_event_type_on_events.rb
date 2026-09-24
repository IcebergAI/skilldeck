class RenameKindToEventTypeOnEvents < ActiveRecord::Migration[7.1]
  def change
    rename_column :events, :kind, :event_type
  end
end
