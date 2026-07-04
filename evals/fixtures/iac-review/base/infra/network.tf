resource "aws_security_group" "app" {
  name   = "app"
  vpc_id = var.vpc_id

  ingress {
    description     = "app traffic from the load balancer"
    from_port       = 8080
    to_port         = 8080
    protocol        = "tcp"
    security_groups = [var.lb_security_group_id]
  }
}
