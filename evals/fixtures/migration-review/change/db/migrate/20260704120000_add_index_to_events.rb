class AddIndexToEvents < ActiveRecord::Migration[7.1]
  def change
    add_index :events, :account_id
  end
end
