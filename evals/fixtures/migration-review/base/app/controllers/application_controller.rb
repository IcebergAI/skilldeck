class ApplicationController < ActionController::API
  after_action :record_event

  private

  def record_event
    Event.create!(
      account: current_account,
      kind: "#{controller_name}.#{action_name}",
      payload: { status: response.status },
      occurred_at: Time.current
    )
  end
end
