# Rack middleware (config.middleware.use RequestEventRecorder): records one
# Event per API request for the signed-in account.
class RequestEventRecorder
  def initialize(app)
    @app = app
  end

  def call(env)
    status, headers, body = @app.call(env)
    account_id = env["app.account_id"]
    if account_id
      request = ActionDispatch::Request.new(env)
      Event.create!(
        account_id: account_id,
        event_type: "#{request.request_method} #{request.path}",
        payload: { status: status },
        occurred_at: Time.current
      )
    end
    [status, headers, body]
  end
end
