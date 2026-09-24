class Event < ApplicationRecord
  belongs_to :account

  validates :event_type, presence: true
end
